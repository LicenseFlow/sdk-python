"""
LicenseFlow Python SDK — Real-Time Revocation & Kill-Switch Stream Listener
==========================================================================
Provides sub-millisecond local kill-switch enforcement and background streaming
for autonomous agent swarms (LangChain, LlamaIndex, AutoGen, CrewAI).

When an operator trips an emergency kill-switch or revokes a license, the listener:
1. Immediately blacklists the subject/license/tool in local memory (< 0.05ms)
2. Invalidates the client's local cache
3. Triggers registered revocation callbacks
4. Halts agent execution loops and tool dispatches before downstream invocation
"""

import threading
import time
import json
import logging
from typing import Callable, Optional, Dict, Any, Set

logger = logging.getLogger("licenseflow.stream")


class RevocationEvent:
    """Represents a received emergency kill-switch or license revocation event."""

    __slots__ = ("target_type", "target_identifier", "reason", "timestamp", "source", "raw_data")

    def __init__(
        self,
        target_type: str,
        target_identifier: str,
        reason: str = "Emergency kill switch tripped by operator",
        timestamp: Optional[float] = None,
        source: str = "stream",
        raw_data: Optional[Dict[str, Any]] = None,
    ):
        self.target_type = target_type          # 'subject', 'license', 'tool', 'organization'
        self.target_identifier = target_identifier
        self.reason = reason
        self.timestamp = timestamp or time.time()
        self.source = source                    # 'poll', 'sse_stream', 'redis_pubsub', 'local'
        self.raw_data = raw_data or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_identifier": self.target_identifier,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    def __repr__(self) -> str:
        return f"<RevocationEvent type={self.target_type} id={self.target_identifier} reason='{self.reason}'>"


class KillSwitchListener:
    """
    Background worker that continuously streams or polls kill-switch states
    and maintains an instant-reject blacklist inside the LicenseFlow client.
    """

    def __init__(
        self,
        client: Any,
        poll_interval: float = 1.0,
        stream_url: Optional[str] = None,
        on_revocation: Optional[Callable[[RevocationEvent], None]] = None,
    ):
        self.client = client
        self.poll_interval = max(0.1, poll_interval)
        self.stream_url = stream_url or f"{client.api_url}/functions/v1/v1-kill-switch"
        self.on_revocation = on_revocation
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the background revocation listener daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="LicenseFlow-KillSwitch-Listener",
                daemon=True,
            )
            self._thread.start()
            logger.info("KillSwitchListener started in background thread")

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the listener to stop and wait for thread termination."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("KillSwitchListener stopped")

    def process_revocation(
        self,
        target_type: str,
        target_identifier: str,
        reason: str = "Emergency shutoff",
        source: str = "stream",
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> RevocationEvent:
        """
        Process a revocation event:
        1. Add target to client's in-memory blacklist
        2. Evict local cache
        3. Notify on_revocation callback
        """
        event = RevocationEvent(
            target_type=target_type.lower(),
            target_identifier=str(target_identifier),
            reason=reason,
            source=source,
            raw_data=raw_data,
        )

        # Update client blacklists
        t_type = event.target_type
        t_id = event.target_identifier

        if t_type in ("subject", "user", "agent"):
            self.client._revoked_subjects.add(t_id)
        elif t_type in ("license", "license_key", "license_id"):
            self.client._revoked_licenses.add(t_id)
        elif t_type in ("tool", "mcp_tool"):
            self.client._revoked_tools.add(t_id)
        else:
            self.client._revoked_subjects.add(t_id)

        # Evict TTLCache / EntitlementCache entries
        try:
            if hasattr(self.client, "cache"):
                # Clear all cache entries that match key
                keys_to_delete = [
                    k for k in list(self.client.cache.keys())
                    if str(t_id) in str(k)
                ]
                for k in keys_to_delete:
                    self.client.cache.pop(k, None)
        except Exception:
            pass

        # Trigger callback
        if self.on_revocation:
            try:
                self.on_revocation(event)
            except Exception as e:
                logger.error("Error in on_revocation callback: %s", e)

        return event

    def _run_loop(self) -> None:
        """Background poll loop checking active kill switches."""
        while not self._stop_event.is_set():
            try:
                self._poll_active_kill_switches()
            except Exception as e:
                logger.debug("Kill switch check error: %s", e)

            # Sleep in small increments to respond quickly to stop_event
            slept = 0.0
            step = 0.2
            while slept < self.poll_interval and not self._stop_event.is_set():
                time.sleep(step)
                slept += step

    def _poll_active_kill_switches(self) -> None:
        """Query the control plane for active kill switches."""
        try:
            resp = self.client.session.get(
                self.stream_url,
                params={"active_only": "true"},
                timeout=3.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                switches = data.get("kill_switches") or data.get("data") or []
                if isinstance(switches, list):
                    for item in switches:
                        if isinstance(item, dict) and item.get("is_active"):
                            t_type = item.get("target_type", "subject")
                            t_id = item.get("target_identifier") or item.get("target_id")
                            reason = item.get("reason", "Operator emergency switch")
                            if t_id:
                                self.process_revocation(t_type, t_id, reason=reason, source="poll", raw_data=item)
        except Exception as e:
            logger.debug("Failed to poll kill switches: %s", e)
