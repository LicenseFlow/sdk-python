import requests
import uuid
import platform
import socket
from cachetools import TTLCache
from jose import jwt
import functools
from .endpoints import CanonicalSession
from .exceptions import (
    LicenseFlowError,
    NetworkError,
    RateLimitError,
    InvalidLicenseError,
    ApprovalRequiredError,
    PolicyDeniedError,
)
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import json
from datetime import datetime

class LicenseFlowClient:
    def __init__(self, api_url, api_key=None, client_token=None, jwt_secret=None, cache_ttl=300, retries=3):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.client_token = client_token
        self.jwt_secret = jwt_secret
        self.cache = TTLCache(maxsize=100, ttl=cache_ttl)
        self.session = CanonicalSession()
        self._revoked_subjects = set()
        self._revoked_licenses = set()
        self._revoked_tools = set()
        self._kill_switch_listener = None
        
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['x-api-key'] = api_key
            headers['Authorization'] = f'Bearer {api_key}'
        if client_token:
            headers['x-client-token'] = client_token
            if not api_key:
                headers['Authorization'] = f'Bearer {client_token}'
        self.session.headers.update(headers)
        
    def authorize(self, subject, resource, action="*", environment=None, region=None, requested_units=None, context=None, dry_run=False):
        """Runtime Authorization Control Plane (POST /v1/authorize)
        
        Evaluates whether a subject (user, agent, service, API client) is entitled
        to perform an action on a protected resource under active policies, quotas, and budgets.
        """
        # Zero-latency local kill-switch pre-flight check
        if self.is_revoked(subject=subject):
            raise PolicyDeniedError(
                f"Subject '{subject}' has been revoked by an active emergency kill switch",
                code="EMERGENCY_REVOKED",
            )

        payload = {
            "subject": subject,
            "resource": resource,
            "action": action,
            "environment": environment,
            "region": region,
            "requested_units": requested_units,
            "context": context or {},
            "dry_run": dry_run,
        }
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/authorize", json=payload)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def check_entitlement(self, subject, resource, action="*"):
        """Check if a subject has explicit entitlement to access a resource.
        Returns True if allowed, False if denied.
        """
        try:
            decision = self.authorize(subject, resource, action=action)
            return bool(decision.get("allowed", False))
        except Exception:
            return False

    def execute_tool(
        self,
        tool: str,
        arguments: dict = None,
        agent_id: str = None,
        subject: str = None,
        mcp_server_id: str = None,
        downstream_url: str = None,
        environment: str = None,
        region: str = None,
        license_key: str = None,
        downstream_headers: dict = None,
    ) -> dict:
        """MCP Enforcement Gateway: Execute Tool with Pre-Flight Runtime Enforcement.
        
        Evaluates policies, emergency kill switches, and human approval gates
        before dispatching downstream.
        """
        target_subject = subject or agent_id or "agent_default"
        # Zero-latency fail-closed pre-flight check: drop if subject, license, or tool revoked
        if self.is_revoked(subject=target_subject, license_key=license_key, tool_name=tool):
            return {
                "allowed": False,
                "decision": "EMERGENCY_REVOKED",
                "status": "revoked",
                "error": f"Tool '{tool}' or subject '{target_subject}' blocked by active kill switch",
                "is_error": True,
                "raw_rpc_response": {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": 20202,
                        "message": f"Action blocked by active kill switch: {tool}",
                        "data": {"decision": "EMERGENCY_REVOKED", "status": "revoked"},
                    },
                },
            }

        rpc_payload = {
            "jsonrpc": "2.0",
            "id": f"call-{uuid.uuid4().hex[:8]}",
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": arguments or {},
                "_meta": {
                    "agent_id": agent_id,
                    "subject": target_subject,
                    "mcp_server_id": mcp_server_id,
                    "downstream_url": downstream_url,
                    "environment": environment,
                    "region": region,
                    "license_key": license_key,
                    "headers": downstream_headers or {},
                },
            },
        }

        headers = {}
        if license_key:
            headers["x-license-key"] = license_key

        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/mcp-gateway",
                json=rpc_payload,
                headers=headers,
            )
            data = response.json()
            if "error" in data:
                err = data["error"]
                err_data = err.get("data") or {}
                decision = err_data.get("decision") or ("REQUIRE_APPROVAL" if err.get("code") == 20201 else "DENY")
                return {
                    "allowed": False,
                    "decision": decision,
                    "status": "pending_approval" if decision == "REQUIRE_APPROVAL" else "denied",
                    "error": err.get("message", "Tool execution denied"),
                    "approval_request_id": err_data.get("approval_request_id"),
                    "is_error": True,
                    "raw_rpc_response": data,
                }

            result = data.get("result", {})
            return {
                "allowed": True,
                "decision": "ALLOW",
                "status": "executed",
                "result": result.get("content", result),
                "is_error": result.get("isError", False),
                "raw_rpc_response": data,
            }
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def list_tools(
        self,
        agent_id: str = None,
        subject: str = None,
        mcp_server_id: str = None,
        downstream_url: str = None,
        license_key: str = None,
    ) -> dict:
        """MCP Enforcement Gateway: List Permitted Tools.
        
        Intercepts tool discovery, filtering out forbidden or unentitled tools.
        """
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": f"list-{uuid.uuid4().hex[:8]}",
            "method": "tools/list",
            "params": {
                "_meta": {
                    "agent_id": agent_id,
                    "subject": subject or agent_id or "agent_default",
                    "mcp_server_id": mcp_server_id,
                    "downstream_url": downstream_url,
                    "license_key": license_key,
                },
            },
        }

        headers = {}
        if license_key:
            headers["x-license-key"] = license_key

        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/mcp-gateway",
                json=rpc_payload,
                headers=headers,
            )
            data = response.json()
            if "error" in data:
                raise LicenseFlowError(data["error"].get("message", "MCP tools/list failed"), code="MCP_LIST_FAILED")
            return {
                "tools": data.get("result", {}).get("tools", []),
                "raw_rpc_response": data,
            }
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def wrap_tool(
        self,
        tool_name: str,
        tool_fn: callable = None,
        agent_id: str = None,
        subject: str = None,
        mcp_server_id: str = None,
        downstream_url: str = None,
        environment: str = None,
        region: str = None,
        license_key: str = None,
    ):
        """Agent Runtime Middleware: Wrap a tool execution handler or function.
        
        Can be used as a decorator or wrapper. Enforces pre-flight authorization,
        blocking unentitled or policy-violating executions before code runs.
        Compatible with LangChain, LlamaIndex, and AutoGen tools.
        """
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                target_sub = subject or agent_id or "agent_default"
                # Immediate check: abort execution if kill switch active
                if self.is_revoked(subject=target_sub, license_key=license_key, tool_name=tool_name):
                    raise PolicyDeniedError(
                        f"Execution of tool '{tool_name}' blocked by active emergency kill switch for subject '{target_sub}'",
                        code="EMERGENCY_REVOKED",
                    )

                tool_args = kwargs if kwargs else (args[0] if len(args) == 1 and isinstance(args[0], dict) else {"args": args})

                # If downstream_url provided, route through central MCP Enforcement Gateway
                if downstream_url:
                    res = self.execute_tool(
                        tool=tool_name,
                        arguments=tool_args,
                        agent_id=agent_id,
                        subject=subject,
                        mcp_server_id=mcp_server_id,
                        downstream_url=downstream_url,
                        environment=environment,
                        region=region,
                        license_key=license_key,
                    )
                    if not res.get("allowed"):
                        if res.get("decision") == "REQUIRE_APPROVAL" and res.get("approval_request_id"):
                            raise ApprovalRequiredError(res["approval_request_id"], res.get("error"))
                        raise PolicyDeniedError(res.get("error", "Execution denied by policy"))
                    return res.get("result")

                # Local execution: run pre-flight policy evaluation
                auth_decision = self.authorize(
                    subject=target_sub,
                    resource=f"tool:{tool_name}",
                    action="execute",
                    environment=environment,
                    region=region,
                    context={"arguments": tool_args, "mcp_server_id": mcp_server_id},
                )

                if not auth_decision.get("allowed"):
                    if auth_decision.get("decision") == "REQUIRE_APPROVAL" and auth_decision.get("approval_request_id"):
                        raise ApprovalRequiredError(auth_decision["approval_request_id"], auth_decision.get("reason"))
                    raise PolicyDeniedError(
                        auth_decision.get("reason", "Policy denied tool execution"),
                        code=auth_decision.get("code", "POLICY_DENIED"),
                    )

                return fn(*args, **kwargs)
            return wrapper

        if tool_fn is not None:
            return decorator(tool_fn)
        return decorator

    # ── Real-Time Revocation & Kill-Switch Methods ─────────────────────────

    def is_revoked(self, subject: str = None, license_key: str = None, tool_name: str = None) -> bool:
        """Sub-millisecond local check if subject, license, or tool is blacklisted."""
        if subject and str(subject) in self._revoked_subjects:
            return True
        if license_key and str(license_key) in self._revoked_licenses:
            return True
        if tool_name and str(tool_name) in self._revoked_tools:
            return True
        return False

    def trip_kill_switch_local(self, target_type: str, target_identifier: str, reason: str = "Emergency shutoff"):
        """Trip an emergency kill-switch locally in memory.
        
        Instantly halts sub-second tool execution and invalidates cached entitlements.
        """
        t_type = target_type.lower()
        t_id = str(target_identifier)
        if t_type in ("subject", "user", "agent"):
            self._revoked_subjects.add(t_id)
        elif t_type in ("license", "license_key", "license_id"):
            self._revoked_licenses.add(t_id)
        elif t_type in ("tool", "mcp_tool"):
            self._revoked_tools.add(t_id)
        else:
            self._revoked_subjects.add(t_id)

        # Evict cache entries
        try:
            keys_to_delete = [k for k in list(self.cache.keys()) if t_id in str(k)]
            for k in keys_to_delete:
                self.cache.pop(k, None)
        except Exception:
            pass

    def reset_kill_switch_local(self, target_identifier: str):
        """Reset a locally blacklisted target identifier."""
        t_id = str(target_identifier)
        self._revoked_subjects.discard(t_id)
        self._revoked_licenses.discard(t_id)
        self._revoked_tools.discard(t_id)

    def start_kill_switch_listener(self, poll_interval: float = 1.0, stream_url: str = None, on_revocation=None):
        """Start the background daemon thread listening for real-time revocations."""
        from .stream import KillSwitchListener
        if self._kill_switch_listener and self._kill_switch_listener.is_running:
            return self._kill_switch_listener

        self._kill_switch_listener = KillSwitchListener(
            client=self,
            poll_interval=poll_interval,
            stream_url=stream_url,
            on_revocation=on_revocation,
        )
        self._kill_switch_listener.start()
        return self._kill_switch_listener

    def stop_kill_switch_listener(self):
        """Stop the background revocation listener thread."""
        if self._kill_switch_listener:
            self._kill_switch_listener.stop()
            self._kill_switch_listener = None

    def protect_agent_swarm(self, subject: str = None):
        """Decorator for LangChain / AutoGen / LlamaIndex agent loops.
        
        Evaluates active kill switches before every invocation. If tripped,
        aborts immediately with PolicyDeniedError (EMERGENCY_REVOKED).
        """
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                sub = subject or kwargs.get("agent_id") or kwargs.get("subject") or "agent_swarm"
                if self.is_revoked(subject=sub):
                    raise PolicyDeniedError(
                        f"Agent swarm '{sub}' halted by active emergency kill switch",
                        code="EMERGENCY_REVOKED",
                    )
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def clear_cache(self):
        """Clear client in-memory cache."""
        self.cache.clear()

    def record_usage_event(self, subject, resource, meter_key, units, dimensions=None, metadata=None, idempotency_key=None):
        """Universal Metering Event Ingestion (POST /v1/meter)
        Records consumption, updates dimensioned meters, and deducts from spending budgets.
        """
        payload = {
            "operation": "record",
            "meter_key": meter_key,
            "subject": subject,
            "resource": resource,
            "units": units,
            "dimensions": dimensions or {},
            "metadata": metadata or {},
            "idempotency_key": idempotency_key,
        }
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/meter", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def revoke(self, target_identifier, reason="Emergency revocation"):
        """Emergency Revocation / Kill Switch Trigger."""
        payload = {
            "targetId": target_identifier,
            "level": "hard",
            "reason": reason,
        }
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/kill-switch", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def get_hardware_id(self):
        """Generate a unique hardware ID for the current machine."""
        try:
            # Simple unique ID using platform and node (MAC address)
            return str(uuid.getnode())
        except Exception:
            return socket.gethostname()

    def activate(self, license_key, device_id=None, device_name=None, hardware_fingerprint=None, is_test=False, environment_id=None):
        """Activate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id,
            "device_name": device_name or socket.gethostname(),
            "hardware_fingerprint": hardware_fingerprint,
            "is_test": is_test,
            "environment_id": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/activate-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def verify(self, license_key, device_id=None, environment_id=None):
        """Verify the license status, using cache if available."""
        if not device_id:
            device_id = self.get_hardware_id()

        return self._verify_with_device(license_key, device_id, environment_id)

    def resolve_for_identity(self, email, product_id=None, environment_id=None):
        """Identity-based (keyless) entitlement resolution.

        Resolve everything an authenticated person is entitled to from their email
        alone -- licenses they own plus any seats assigned to them -- without
        handling a license key. Authenticate the user in your own app or IDP
        first, then call this from your backend with the verified email.
        """
        cache_key = f"identity:{email}:{product_id or 'all'}:{environment_id or 'default'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        payload = {
            "email": email,
            "productId": product_id,
            "environmentId": environment_id,
        }

        try:
            response = self.session.post(f"{self.api_url}/functions/v1/resolve-entitlements", json=payload)
            self._handle_response_errors(response)
            data = response.json()

            if data.get("resolved"):
                self.cache[cache_key] = data

            return data
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def _verify_with_device(self, license_key, device_id, environment_id=None):
        """Internal: perform the device-bound verification request."""
            
        cache_key = f"verify:{license_key}:{device_id}:{environment_id or 'default'}"
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        payload = {
            "licenseKey": license_key,
            "deviceId": device_id,
            "environmentId": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/verify-license", json=payload)
            self._handle_response_errors(response)
            data = response.json()
            
            if data.get("valid"):
                self.cache[cache_key] = data
                
            return data
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def record_usage(self, license_key, metric_name, value, increment=False, is_test=False, environment_id=None):
        """Record usage metrics for a license (legacy)."""
        payload = {
            "license_key": license_key,
            "metric_name": metric_name,
            "value": value,
            "increment": increment,
            "is_test": is_test,
            "environment_id": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/record-usage", json=payload)
            self._handle_response_errors(response)
            return {"success": True, **response.json()}
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def track_usage(self, event, quantity=1, unit="units", license_key=None, customer_id=None, idempotency_key=None, dimensions=None, metadata=None):
        """
        Track commercial telemetry events with idempotency and real-time quota feedback.
        Returns a dict with success, event_id, quota_status, quota_policy, is_duplicate, and usage.
        """
        payload = {
            "event_name": event,
            "metric_name": event,
            "quantity": quantity,
            "unit": unit,
            "license_key": license_key,
            "customer_id": customer_id,
            "idempotency_key": idempotency_key,
            "dimensions": dimensions or {},
            "metadata": metadata or {}
        }
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/record-usage", json=payload)
            data = response.json() if response.content else {}
            if response.status_code == 429:
                return {
                    "success": False,
                    "blocked": True,
                    "error": data.get("error", "QUOTA_EXCEEDED"),
                    "status": "exceeded",
                    "action": "BLOCK",
                    "usage": data.get("usage", {})
                }
            self._handle_response_errors(response)
            return {
                "success": True,
                "event_id": data.get("event_id"),
                "is_duplicate": data.get("is_duplicate", False),
                "status": data.get("status", "normal"),
                "action": data.get("action", "ALLOW"),
                "usage": data.get("usage", {}),
                **data
            }
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def deactivate(self, license_key, device_id=None, environment_id=None):
        """Deactivate a license for this device."""
        if not device_id:
            device_id = self.get_hardware_id()
            
        payload = {
            "license_key": license_key,
            "device_id": device_id,
            "environment_id": environment_id
        }
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/deactivate-license", json=payload)
            self._handle_response_errors(response)
            self.clear_cache()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def validate_proof_offline(self, proof, secret=None):
        """Validate a signed proof token offline."""
        key = secret or self.jwt_secret
        if not key:
            raise ValueError("JWT Secret is required for offline validation")
            
        try:
            payload = jwt.decode(proof, key, algorithms=['HS256'])
            return {
                "valid": True,
                "payload": payload
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e)
            }

    def _handle_response_errors(self, response):
        """Raise appropriate exceptions based on response status code."""
        if response.status_code == 200:
            return
            
        # Clear cache on any error to be safe
        self.cache.clear()
            
        message = None
        try:
            data = response.json()
            if isinstance(data, dict):
                message = data.get("message") or data.get("error") or data.get("msg")
        except Exception:
            pass
            
        if not message:
            message = response.text or f"HTTP {response.status_code}"
            
        if response.status_code == 429:
            raise RateLimitError(message)
        elif response.status_code in [400, 404]:
            raise InvalidLicenseError(message)
        elif response.status_code >= 500:
            raise NetworkError(message)
        else:
            raise LicenseFlowError(message, status=response.status_code)

    def has_feature(self, verification, feature_code):
        """
        Phase 5: Check if license has a feature enabled
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return False
        
        ent = verification['entitlements'].get(feature_code)
        if ent is None:
            return False
        
        # Handle different value formats
        if isinstance(ent, bool):
            return ent
        if isinstance(ent, dict):
            return ent.get('enabled') is True or ent.get('value') is True
        return ent is True

    def get_entitlement(self, verification, feature_code):
        """
        Phase 5: Get entitlement value
        """
        if not verification.get('valid') or not verification.get('entitlements'):
            return None
        return verification['entitlements'].get(feature_code)

    def check_for_updates(self, current_version, product_id, channel='stable'):
        """Check for software updates."""
        try:
            response = self.session.get(
                f'{self.api_url}/functions/v1/release-management/latest',
                params={
                    'product_id': product_id,
                    'channel': channel
                }
            )
            
            # Handle 404 before error handler — no update available
            if response.status_code == 404:
                return None
            
            self._handle_response_errors(response)
            
            try:
                data = response.json()
            except ValueError:
                return None

            if not data or data.get('version') == current_version:
                return None
            
            return {
                'id': data['id'],
                'version': data['version'],
                'changelog': data.get('changelog'),
                'published_at': data['published_at']
            }
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def checkout_license(self, license_key, duration_seconds=3600, requester_id=None, requester_type='ci', metadata=None):
        """Acquire a temporary floating license lease."""
        payload = {
            "license_key": license_key,
            "duration_seconds": duration_seconds,
            "requester_id": requester_id or self.get_hardware_id(),
            "requester_type": requester_type,
        }
        if metadata:
            payload["metadata"] = metadata
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/checkout-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def checkin_license(self, lease_key):
        """Release a floating license lease early."""
        payload = {"lease_key": lease_key}
        
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/checkin-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def get_lease_status(self, lease_key):
        """Check the status and remaining time of a lease."""
        try:
            response = self.session.get(
                f"{self.api_url}/functions/v1/lease-status",
                params={"lease_key": lease_key}
            )
            if response.status_code == 404:
                return None
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    # ── Credits / Usage-Based Billing ──

    def consume_credits(self, amount, description=None, product_id=None, currency='credits', reference_id=None, reference_type=None, metadata=None):
        """Consume credits from the organization's balance."""
        payload = {"amount": amount}
        if description:
            payload["description"] = description
        if product_id:
            payload["product_id"] = product_id
        if currency != 'credits':
            payload["currency"] = currency
        if reference_id:
            payload["reference_id"] = reference_id
        if reference_type:
            payload["reference_type"] = reference_type
        if metadata:
            payload["metadata"] = metadata

        try:
            response = self.session.post(f"{self.api_url}/functions/v1/consume-credits", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def get_credits_balance(self, product_id=None, currency=None):
        """Get credit balance for the organization."""
        params = {}
        if product_id:
            params["product_id"] = product_id
        if currency:
            params["currency"] = currency

        try:
            response = self.session.get(f"{self.api_url}/functions/v1/get-credit-balance", params=params)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    # ── Entitlements Management ──

    def list_entitlements(self):
        """List all entitlements for the organization."""
        try:
            response = self.session.get(f"{self.api_url}/functions/v1/manage-entitlements")
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def create_entitlement(self, code, name, data_type='boolean', description=None, metadata=None):
        """Create a new entitlement definition."""
        payload = {"code": code, "name": name, "data_type": data_type}
        if description:
            payload["description"] = description
        if metadata:
            payload["metadata"] = metadata

        try:
            response = self.session.post(f"{self.api_url}/functions/v1/manage-entitlements", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def update_entitlement(self, entitlement_id, **kwargs):
        """Update an existing entitlement definition."""
        try:
            response = self.session.patch(f"{self.api_url}/functions/v1/manage-entitlements/{entitlement_id}", json=kwargs)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def delete_entitlement(self, entitlement_id):
        """Delete an entitlement definition."""
        try:
            response = self.session.delete(f"{self.api_url}/functions/v1/manage-entitlements/{entitlement_id}")
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def assign_entitlement_to_license(self, entitlement_id, license_id, value):
        """Assign an entitlement to a specific license."""
        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/manage-entitlements/{entitlement_id}/assign-to-license",
                json={"license_id": license_id, "value": value}
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def assign_entitlement_to_policy(self, entitlement_id, policy_id, default_value):
        """Assign an entitlement to a policy (as default)."""
        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/manage-entitlements/{entitlement_id}/assign-to-policy",
                json={"policy_id": policy_id, "default_value": default_value}
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def download_artifact(self, license_key, release_id=None, artifact_id=None, platform=None, architecture=None):
        """
        Phase 5: Download artifact with license verification
        """
        payload = {
            'license_key': license_key,
            'release_id': release_id,
            'artifact_id': artifact_id,
            'platform': platform,
            'architecture': architecture
        }
        
        try:
            response = self.session.post(
                f'{self.api_url}/functions/v1/artifact-download',
                json=payload
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def verify_offline_license(self, license_file, public_key):
        """
        Phase 5: Verify offline license signature
        """
        try:
            data = json.loads(license_file)
            
            if 'license' not in data or 'signature' not in data:
                raise ValueError('Invalid offline license format')
            
            # Prepare message and signature
            # Use separators to match JS JSON.stringify behavior if needed, usually default is slightly different in Python (spaces)
            # Standard: separators=(',', ':') removes spaces
            message = json.dumps(data['license'], separators=(',', ':')).encode()
            signature = base64.b64decode(data['signature'])
            pub_key_bytes = bytes.fromhex(public_key)
            
            # Verify Ed25519 signature
            public_key_obj = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
            
            try:
                public_key_obj.verify(signature, message)
            except Exception:
                raise ValueError('Invalid offline license signature')
            
            # Check expiration
            valid_until_str = data['license']['valid_until']
            # Simple ISO parsing (python 3.7+ supports fromisoformat, prior needs dateutil)
            # Removing Z for compatibility if needed, but 3.11 supports Z
            if valid_until_str.endswith('Z'):
                valid_until_str = valid_until_str[:-1] + '+00:00'
                
            valid_until = datetime.fromisoformat(valid_until_str)
            
            if valid_until < datetime.now(valid_until.tzinfo):
                raise ValueError('Offline license has expired')
            
            return data['license']
            
        except json.JSONDecodeError:
            raise ValueError('Invalid JSON format in license file')
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f'Failed to verify offline license: {str(e)}')

    # ── Floating License Lease Methods ──

    def checkout_license(self, license_key, duration_seconds=3600, requester_id=None, requester_type="sdk", metadata=None):
        """Acquire a temporary floating license lease."""
        payload = {
            "license_key": license_key,
            "duration_seconds": duration_seconds,
            "requester_id": requester_id or self.get_hardware_id(),
            "requester_type": requester_type,
            "metadata": metadata or {},
        }
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/checkout-license", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def checkin_license(self, lease_key):
        """Release (check-in) a floating license lease."""
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/checkin-license", json={"lease_key": lease_key})
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def get_lease_status(self, lease_key):
        """Get the status of a floating license lease."""
        try:
            response = self.session.post(f"{self.api_url}/functions/v1/lease-status", json={"lease_key": lease_key})
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    # ── Token & Credit Metering ──

    def meter_usage(self, metric_name, value=1, license_key=None, client_token=None, metadata=None):
        """Record usage or decrement units for token-metered licenses."""
        headers = {}
        if client_token:
            headers["x-client-token"] = client_token
            headers["Authorization"] = f"Bearer {client_token}"

        payload = {
            "metric_name": metric_name,
            "metric_value": value,
            "metadata": metadata or {},
        }
        if license_key:
            payload["license_key"] = license_key

        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/record-usage",
                json=payload,
                headers=headers or None
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def consume_credits(self, amount, description=None, product_id=None, currency="credits", reference_id=None, reference_type=None, metadata=None):
        """Consume credits from the organization's credit pool."""
        payload = {
            "amount": amount,
            "description": description or "API consumption",
            "currency": currency,
            "metadata": metadata or {},
        }
        if product_id:
            payload["product_id"] = product_id
        if reference_id:
            payload["reference_id"] = reference_id
        if reference_type:
            payload["reference_type"] = reference_type

        try:
            response = self.session.post(f"{self.api_url}/functions/v1/consume-credits", json=payload)
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    # ── AI Token Budget & Gateway (License-key auth) ─────────────────────

    def ai_token_budget(self, license_key, requested_tokens=0):
        """Check AI token budget for a license key.

        Returns quota, used, remaining, allowed models, and whether
        a given token count fits within the remaining budget.

        Args:
            license_key: The software license key to check.
            requested_tokens: Optional token count to check sufficiency.

        Returns:
            dict with has_quota, quota, used, remaining, sufficient, allowed_models.
        """
        payload = {
            "p_license_id": license_key,
            "p_requested_tokens": requested_tokens,
        }
        try:
            response = self.session.post(
                f"{self.api_url}/rest/v1/rpc/check_ai_token_budget",
                json=payload
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

    def ai_gateway_chat(self, license_key, model, messages, subject="sdk_agent",
                        temperature=0.7, max_tokens=1000, stream=False, metadata=None):
        """Send a chat completion through the AI Gateway using a license key.

        The license key must have an ai_token_quota entitlement attached.

        Args:
            license_key: The software license key for authentication.
            model: Model identifier (e.g., 'gpt-4', 'claude-3-sonnet').
            messages: List of message dicts with 'role' and 'content'.
            subject: Agent/subject identifier for audit trails.
            temperature: Sampling temperature (0-2).
            max_tokens: Maximum tokens in the response.
            stream: Whether to stream the response.
            metadata: Additional metadata dict.

        Returns:
            Chat completion response with licenseflow_meta.
        """
        payload = {
            "model": model,
            "messages": messages,
            "subject": subject,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "metadata": metadata or {},
        }
        try:
            response = self.session.post(
                f"{self.api_url}/functions/v1/ai-gateway",
                json=payload,
                headers={"x-license-key": license_key}
            )
            self._handle_response_errors(response)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))

