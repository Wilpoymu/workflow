export default defineContentScript({
  matches: ["https://labs.google/fx/*/tools/flow*", "https://labs.google/fx/tools/flow*"],
  world: "MAIN",
  main() {
    var SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV";
    var RECAPTCHA_ACTION = "IMAGE_GENERATION";
    var TOKEN_POOL_SIZE = 5;
    var TOKEN_MAX_AGE_MS = 100000;
    var _tokenPool: { token: string; time: number }[] = [];
    var _tokenFetching = 0;
    var _maxTokenFetching = 3;
    var _bearer: string | null = null;

    function _getToken(): Promise<string> {
      return new Promise(function (resolve, reject) {
        var now = Date.now();
        while (_tokenPool.length > 0) {
          var entry = _tokenPool.shift()!;
          if (now - entry.time < TOKEN_MAX_AGE_MS) {
            _refillPool();
            resolve(entry.token);
            return;
          }
        }
        _refillPool();
        if (typeof (window as any).grecaptcha === "undefined" || !(window as any).grecaptcha.enterprise) {
          reject(new Error("grecaptcha not available"));
          return;
        }
        (window as any).grecaptcha.enterprise.ready(function () {
          (window as any).grecaptcha.enterprise
            .execute(SITE_KEY, { action: RECAPTCHA_ACTION })
            .then(function (t: string) {
              resolve(t);
              _refillPool();
            })
            .catch(reject);
        });
      });
    }

    function _fetchOneToken() {
      if (typeof (window as any).grecaptcha === "undefined" || !(window as any).grecaptcha.enterprise) return;
      if (_tokenFetching >= _maxTokenFetching) return;
      _tokenFetching++;
      (window as any).grecaptcha.enterprise.ready(function () {
        (window as any).grecaptcha.enterprise
          .execute(SITE_KEY, { action: RECAPTCHA_ACTION })
          .then(function (t: string) {
            _tokenFetching--;
            if (_tokenPool.length < TOKEN_POOL_SIZE) {
              _tokenPool.push({ token: t, time: Date.now() });
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

    function djb2Hash(str: string): string {
      var h = 5381;
      for (var i = 0; i < str.length; i++) {
        h = ((h << 5) + h + str.charCodeAt(i)) & 0xffffffff;
      }
      var hex = (h >>> 0).toString(16);
      while (hex.length < 8) hex = "0" + hex;
      return hex;
    }

    function doGenerateRequest(data: { batchId: string; requests: any[] }) {
      var batchId = data.batchId;
      var requests = data.requests || [];

      if (requests.length === 0) return;

      Promise.all(
        requests.map(function (req) {
          return _getToken().then(function (token) {
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
              return r.text().then(function (text) {
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
        .catch(function () {});
    }

    window.addEventListener("message", function (event) {
      if (event.source !== window) return;
      if (!event.data) return;
      if (event.data.type === "FLOW_GENERATE_REQUEST") {
        doGenerateRequest(event.data);
      }
    });

    // Wait for grecaptcha
    var attempts = 0;
    var waitInterval = setInterval(function () {
      attempts++;
      if (typeof (window as any).grecaptcha !== "undefined" && (window as any).grecaptcha.enterprise) {
        clearInterval(waitInterval);
        _refillPool();
      }
      if (attempts > 120) clearInterval(waitInterval);
    }, 500);

    // Auto-auth: fetch session and post to backend
    fetch("/fx/api/auth/session", { credentials: "include" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _bearer = data.access_token;
        var user = data.user || {};
        var identity = user.email || user.name || "";
        if (identity) {
          var hash = djb2Hash(identity);
          window.postMessage({ type: "FLOW_ACCOUNT_HASH", hash: hash, email: user.email || "" }, "*");

          (function sendAuth(attempt: number) {
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
                if (!r.ok && attempt < 5) {
                  setTimeout(function () { sendAuth(attempt + 1); }, 3000);
                }
              })
              .catch(function () {
                if (attempt < 5) {
                  setTimeout(function () { sendAuth(attempt + 1); }, 3000);
                }
              });
          })(1);
        }
      })
      .catch(function () {});

    // Refresh session every 60s
    setInterval(function () {
      fetch("/fx/api/auth/session", { credentials: "include" })
        .then(function (r) { return r.json(); })
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
  },
})
