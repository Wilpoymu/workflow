var SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV";
var RECAPTCHA_ACTION = "IMAGE_GENERATION";
var TOKEN_POOL_SIZE = 5;
var TOKEN_MAX_AGE_MS = 100000;
var _tokenPool = [];
var _tokenFetching = 0;
var _maxTokenFetching = 3;
var _bearer = null;

function _getToken() {
  return new Promise(function (resolve, reject) {
    var now = Date.now();
    while (_tokenPool.length > 0) {
      var entry = _tokenPool.shift();
      if (now - entry.time < TOKEN_MAX_AGE_MS) {
        _refillPool();
        resolve(entry.token);
        return;
      }
    }
    _refillPool();
    if (typeof grecaptcha === "undefined" || !grecaptcha.enterprise) {
      reject(new Error("grecaptcha not available"));
      return;
    }
    grecaptcha.enterprise.ready(function () {
      grecaptcha.enterprise
        .execute(SITE_KEY, { action: RECAPTCHA_ACTION })
        .then(function (t) {
          resolve(t);
          _refillPool();
        })
        .catch(reject);
    });
  });
}

function _fetchOneToken() {
  if (typeof grecaptcha === "undefined" || !grecaptcha.enterprise) return;
  if (_tokenFetching >= _maxTokenFetching) return;
  _tokenFetching++;
  grecaptcha.enterprise.ready(function () {
    grecaptcha.enterprise
      .execute(SITE_KEY, { action: RECAPTCHA_ACTION })
      .then(function (t) {
        _tokenFetching--;
        if (_tokenPool.length < TOKEN_POOL_SIZE) {
          _tokenPool.push({ token: t, time: Date.now() });
          console.log("[TokenGen] Token pre-fetched (pool=" + _tokenPool.length + ")");
        }
      })
      .catch(function () {
        _tokenFetching--;
      });
  });
}

function _refillPool() {
  var needed = TOKEN_POOL_SIZE - _tokenPool.length - _tokenFetching;
  for (var i = 0; i < needed; i++) {
    _fetchOneToken();
  }
}

function djb2Hash(str) {
  var h = 5381;
  for (var i = 0; i < str.length; i++) {
    h = ((h << 5) + h + str.charCodeAt(i)) & 0xffffffff;
  }
  var hex = (h >>> 0).toString(16);
  while (hex.length < 8) hex = "0" + hex;
  return hex;
}

function doGenerateRequest(data) {
  var batchId = data.batchId;
  var requests = data.requests || [];

  if (requests.length === 0) return;

  Promise.all(
    requests.map(function (req) {
      return _getToken().then(function (token) {
        var promptPreview = req.body && req.body.requests && req.body.requests[0] && req.body.requests[0].structuredPrompt && req.body.requests[0].structuredPrompt.parts && req.body.requests[0].structuredPrompt.parts[0] ? req.body.requests[0].structuredPrompt.parts[0].text.substring(0, 40) : "?";
        console.log("[TokenGen] Generating request=" + req.requestId + " prompt=" + promptPreview + "...");
        var body = req.body;
        body.clientContext = body.clientContext || {};
        body.clientContext.recaptchaContext = {
          token: token,
          applicationType: "RECAPTCHA_APPLICATION_TYPE_WEB",
        };
        if (body.requests && body.requests.length > 0) {
          body.requests[0].clientContext = body.requests[0].clientContext || {};
          body.requests[0].clientContext.recaptchaContext = {
            token: token,
            applicationType: "RECAPTCHA_APPLICATION_TYPE_WEB",
          };
        }
        return fetch(req.url, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + _bearer,
          },
          body: JSON.stringify(body),
        }).then(function (r) {
          console.log("[TokenGen] Fetch done request=" + req.requestId + " url=" + req.url + " status=" + r.status);
          return r.text().then(function (text) {
            console.log("[TokenGen] Response request=" + req.requestId + " status=" + r.status + " body=" + text.substring(0, 300));
            return { requestId: req.requestId, success: r.status === 200, status: r.status, data: text };
          });
        });
      });
    })
  )
    .then(function (results) {
      window.postMessage(
        { type: "FLOW_GENERATE_RESULT", batchId: batchId, results: results },
        "*"
      );
    })
    .catch(function (e) {
      window.postMessage(
        {
          type: "FLOW_GENERATE_RESULT",
          batchId: batchId,
          results: [{ error: e.toString() }],
        },
        "*"
      );
    });
}

window.addEventListener("message", function (event) {
  if (event.source !== window) return;
  if (!event.data) return;
  if (event.data.type === "FLOW_GENERATE_REQUEST") {
    console.log("[TokenGen] Generate request received, batch=" + event.data.batchId + " requests=" + (event.data.requests || []).length);
    doGenerateRequest(event.data);
  }
});

var attempts = 0;
var waitInterval = setInterval(function () {
  attempts++;
  if (typeof grecaptcha !== "undefined" && grecaptcha.enterprise) {
    clearInterval(waitInterval);
    console.log("[TokenGen] grecaptcha ready");
    _refillPool();
  }
  if (attempts > 120) clearInterval(waitInterval);
}, 500);

fetch("/fx/api/auth/session", { credentials: "include" })
  .then(function (r) {
    return r.json();
  })
  .then(function (data) {
    _bearer = data.access_token;
    var user = data.user || {};
    var identity = user.email || user.name || "";
    if (identity) {
      var hash = djb2Hash(identity);
      window.postMessage({ type: "FLOW_ACCOUNT_HASH", hash: hash, email: user.email || "" }, "*");
      console.log("[TokenGen] Account hash: " + hash + " (" + identity + ")");

      (function sendAuth(attempt) {
        fetch("http://127.0.0.1:8000/api/auth/auto", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account: hash,
            token: data.access_token,
            email: user.email || "",
          }),
        })
          .then(function (r) {
            if (r.ok) {
              console.log("[TokenGen] Auto-auth sent OK (attempt " + attempt + ")");
            } else if (attempt < 5) {
              setTimeout(function () {
                sendAuth(attempt + 1);
              }, 3000);
            }
          })
          .catch(function (e) {
            if (attempt < 5) {
              console.log("[TokenGen] Auto-auth retry " + attempt + "/5: " + e.message);
              setTimeout(function () {
                sendAuth(attempt + 1);
              }, 3000);
            } else {
              console.log("[TokenGen] Auto-auth failed after 5 attempts");
            }
          });
      })(1);
    }
  })
  .catch(function (e) {
    console.log("[TokenGen] Could not get session: " + e.message);
  });

setInterval(function () {
  fetch("/fx/api/auth/session", { credentials: "include" })
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      _bearer = data.access_token;
      var user = data.user || {};
      var identity = user.email || user.name || "";
      if (identity) {
        var hash = djb2Hash(identity);
        fetch("http://127.0.0.1:8000/api/auth/auto", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account: hash,
            token: data.access_token,
            email: user.email || "",
          }),
        }).catch(function () {});
      }
    })
    .catch(function () {});
}, 60000);
