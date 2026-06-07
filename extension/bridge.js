var WS_URL = "ws://127.0.0.1:8766";
var _ws = null;
var _accountHash = null;
var _accountEmail = null;

function wsConnect() {
  if (_ws && (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)) return;
  try {
    _ws = new WebSocket(WS_URL);
  } catch (e) {
    setTimeout(wsConnect, 2000);
    return;
  }
  _ws.onopen = function () {
    console.log("[Workflow Bridge] WS connected");
    if (_accountHash) {
      _ws.send(JSON.stringify({ type: "register", account: _accountHash, email: _accountEmail }));
    }
  };
  _ws.onmessage = function (event) {
    try {
      var msg = JSON.parse(event.data);
      if (msg.type === "generate" && msg.requests) {
        console.log("[Workflow Bridge] WS got generate batch=" + msg.batchId + " requests=" + msg.requests.length);
        window.postMessage(
          {
            type: "FLOW_GENERATE_REQUEST",
            requests: msg.requests,
            batchId: msg.batchId,
          },
          "*"
        );
      }
    } catch (e) {
      console.log("[Workflow Bridge] WS message error: " + e.message);
    }
  };
  _ws.onclose = function () {
    console.log("[Workflow Bridge] WS disconnected, reconnecting in 2s");
    _ws = null;
    setTimeout(wsConnect, 2000);
  };
  _ws.onerror = function () {
    _ws.close();
  };
}

window.addEventListener("message", function (event) {
  if (event.source !== window) return;
  if (!event.data) return;

  if (event.data.type === "FLOW_ACCOUNT_HASH") {
    _accountHash = event.data.hash;
    _accountEmail = event.data.email || null;
    console.log("[Workflow Bridge] Account hash set: " + _accountHash + " email: " + (_accountEmail || "N/A"));
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: "register", account: _accountHash, email: _accountEmail }));
    }
    return;
  }

  if (event.data.type === "FLOW_GENERATE_RESULT") {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(
        JSON.stringify({
          type: "result",
          batchId: event.data.batchId,
          results: event.data.results,
        })
      );
      console.log("[Workflow Bridge] WS result sent for batch=" + event.data.batchId);
    }
  }
});

wsConnect();
console.log("[Workflow Bridge] Bridge script loaded, WS=" + WS_URL);
