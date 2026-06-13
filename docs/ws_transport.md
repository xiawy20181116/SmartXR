# WSTransport subsystem (Godot)

`godot-android/scripts/ws_transport.gd` (`WSTransport`) wraps a single
`WebSocketPeer` connection loop. The card uses two instances: one for keyboard
control and one for the proxy_targets live stream.

The transport owns connection, polling, retry, and optional subscribe-once
behavior. The card owns URL resolution, enable gates, packet interpretation,
and status text.

## Boundary

WSTransport owns:

- Creating and polling `WebSocketPeer`.
- Connecting to the current URL.
- Sending one optional subscribe payload after the socket opens.
- Draining incoming packets and forwarding packet text to a callback.
- Tracking connection state, packet count, last packet size, and retry timer.
- Retrying after closed sockets.

`AndroidMovingCard.gd` still owns:

- Choosing the URL via `SmartXROptions`.
- Deciding whether a transport should run.
- Parsing control commands and proxy_targets messages.
- Formatting connection errors for the status snapshot.
- Updating cards, targets, and diagnostics from packets.

## Public surface

| API | Caller | Meaning |
|---|---|---|
| `set_on_packet(callable)` | Card setup | Receives packet text for each incoming WebSocket packet. |
| `set_subscribe_payload(payload)` | proxy_targets setup | Sets an optional text payload sent once after connection. |
| `set_on_connect_error(callable)` | Card setup | Reports synchronous `connect_to_url` errors. |
| `set_url_provider(callable)` | Card setup / probes | Supplies the URL for reconnect attempts. |
| `connect_to(url)` | Card setup / reconnect | Opens the socket and records `current_url`. |
| `poll(delta)` | Card `_process` path | Polls the socket, drains packets, sends subscribe, and advances retry. |
| `ws_connected()` | Status snapshot | True when the socket state is open. |
| `ws_subscribed()` | Status snapshot | True after the subscribe payload has been sent. |
| `packets_seen()` | Status snapshot | Count of packets delivered to `on_packet`. |
| `last_packet_bytes()` | Status snapshot | Byte size of the most recent packet. |
| `retry_seconds()` | Status/probes | Seconds accumulated toward the next reconnect. |
| `current_url()` | Status snapshot | Last URL passed to `connect_to`. |

Closed sockets retry after `RETRY_ON_CLOSE_SECONDS` (2.0 s).

## Runtime behavior

The caller typically wires the transport once, then calls `poll(delta)` every
frame. `poll()` handles four cases:

| Socket state | Behavior |
|---|---|
| Open | Send subscribe payload if needed, then drain all available packets. |
| Connecting / closing | Poll only. |
| Closed | Accumulate retry time and reconnect through the URL provider. |
| Connect error | Report through `on_connect_error` and wait for retry. |

The subscribe path uses `send_text()`. Godot 4's `WebSocketPeer` does not
provide the old `set_write_mode()` API, so the transport avoids that latent
failure mode.

## Runtime verification

```powershell
powershell -File tools\run_godot_ws_transport_probe.ps1
```

The probe runs `godot-android/tests/script_only_ws_transport_probe.gd` in
no-project mode. It verifies packet delivery, subscribe-once behavior,
connection state, packet byte accounting, connect-error reporting, and retry
against an accept-then-close listener.

Python coverage:

```powershell
python -m unittest tests.test_godot_ws_transport
```

## Extending WSTransport

1. Keep packet semantics outside the transport; packet callbacks should receive
   text and let the caller parse it.
2. Keep URL and feature-gate decisions in the caller.
3. Update the Godot probe for connection-state changes, because WebSocketPeer
   behavior differs between closed ports and failed handshakes on Windows.
4. Keep probe-visible code free of self-references to `WSTransport` return
   types, because no-project mode does not register global classes.
