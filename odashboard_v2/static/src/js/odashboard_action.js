/** @odoo-module */

import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { jsonrpc } from "@web/core/network/rpc_service";
import { cookie } from "@web/core/browser/cookie";

/**
 * ODashboard Client Action
 *
 * Renders a full-screen iframe pointing to the ODashboard frontend.
 * On mount, it calls /odashboard/iframe-token to get a signed HMAC token,
 * then constructs the URL: {frontend_url}/load?token={base64(token)}&iframe=1
 *
 * When instance_key is missing, loads {frontend_url}/setup?iframe=1 instead
 * (in-app onboarding guide).
 *
 * Error handling:
 *   - not_configured: api_url or frontend_url missing → Odoo-native setup screen
 *   - iframe_error: iframe failed to load (wrong URL, network) → connection error screen
 *
 * postMessage protocol (iframe → parent):
 *   - odashboard-ready: iframe app loaded successfully
 *   - odashboard-reauth: request fresh HMAC token
 *   - odashboard-reload: request full iframe reload (e.g. after logout)
 *   - odashboard-navigate: open an Odoo record/list
 *   - odashboard-open-settings: open Odoo Settings > ODashboard
 *   - odashboard-open-external: open a URL in a new browser tab
 *   - odashboard-redirect: navigate the parent window to a URL (e.g. after iframe auth link flow)
 */

// After the iframe fires its native `load` event, how long to wait for the
// odashboard-ready postMessage before concluding the URL is wrong (ms).
// Connection-refused pages fire `load` almost instantly, so this keeps detection fast.
const IFRAME_POST_LOAD_TIMEOUT = 2000;

// Absolute maximum wait time — fallback for very slow networks where the
// iframe hasn't even fired `load` yet (ms).
const IFRAME_MAX_TIMEOUT = 15000;

class ODashboardAction extends Component {
    static template = "odashboard_client.ODashboardAction";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        try {
            this.companyService = useService("company");
        } catch {
            this.companyService = null;
        }
        this.iframeRef = useRef("iframe");
        this._iframeLoadTimer = null;
        this._iframeAlive = false;

        this.state = useState({
            iframeSrc: null,
            loading: true,
            // Error state: null | "not_configured" | "iframe_error" | "generic"
            errorType: null,
            // For not_configured: which fields are missing
            missingFields: [],
            // For generic errors: message text
            errorMessage: null,
        });

        // Bound handler for cleanup
        this._onMessage = this._onMessage.bind(this);

        onWillStart(async () => {
            await this.loadIframeToken();
        });

        onMounted(() => {
            window.addEventListener("message", this._onMessage);
            this._startIframeLoadCheck();
        });

        onWillUnmount(() => {
            window.removeEventListener("message", this._onMessage);
            this._cleanupIframeListeners();
        });
    }

    async loadIframeToken() {
        try {
            const result = await jsonrpc("/odashboard/iframe-token", {});

            if (result.error) {
                if (result.error === "not_configured") {
                    this.state.errorType = "not_configured";
                    this.state.missingFields = result.missing || [];
                    this.state.loading = false;
                    return;
                }
                // Legacy or unexpected error string
                this.state.errorType = "generic";
                this.state.errorMessage = result.error;
                this.state.loading = false;
                return;
            }

            // Instance key missing → load the in-app setup page
            if (result.needs_setup && result.frontend_url) {
                const frontend_url = result.frontend_url;
                this._frontendOrigin = new URL(frontend_url).origin;
                this.state.iframeSrc = `${frontend_url}/setup?iframe=1`;
                this.state.loading = false;
                return;
            }

            const { token, frontend_url } = result;

            if (!token || !frontend_url) {
                this.state.errorType = "not_configured";
                this.state.missingFields = [];
                this.state.loading = false;
                return;
            }

            // Store frontend URL for secure postMessage targeting
            this._frontendOrigin = new URL(frontend_url).origin;

            // Inject currently selected company IDs from Odoo's company switcher.
            // These are NOT part of the HMAC signature — they are informational
            // context, similar to odoo_name/odoo_login.
            token.company_ids = this._getAllowedCompanyIds();

            // Base64-encode the token object and construct the /load URL
            const tokenB64 = this._unicodeSafeB64Encode(JSON.stringify(token));
            this.state.iframeSrc = `${frontend_url}/load?token=${encodeURIComponent(tokenB64)}&iframe=1`;
            this.state.loading = false;
        } catch (e) {
            console.error("ODashboard: Failed to generate iframe token", e);
            this.state.errorType = "generic";
            this.state.errorMessage =
                "Unable to connect to the Odoo server. Please reload the page.";
            this.state.loading = false;
        }
    }

    /**
     * Start iframe load detection.
     *
     * Two-phase strategy:
     * 1. Listen for the iframe's native `load` event. When it fires (even on
     *    error pages like ERR_CONNECTION_REFUSED), start a short timer
     *    (IFRAME_POST_LOAD_TIMEOUT) waiting for `odashboard-ready`.
     * 2. A global fallback timer (IFRAME_MAX_TIMEOUT) catches cases where the
     *    iframe never fires `load` at all (e.g. DNS hanging).
     *
     * If `odashboard-ready` arrives at any point, both timers are cleared.
     */
    _startIframeLoadCheck() {
        // Only check if we actually have an iframe to load
        if (!this.state.iframeSrc || this.state.errorType) {
            return;
        }
        this._iframeAlive = false;

        // Phase 1: listen for the native load event on the iframe element.
        // We use requestAnimationFrame to ensure the DOM has the iframe.
        requestAnimationFrame(() => {
            const iframe = this.iframeRef.el;
            if (iframe && !this._iframeAlive) {
                this._onIframeLoad = () => {
                    if (this._iframeAlive) return; // already confirmed alive
                    // The iframe loaded *something* (could be an error page).
                    // Give the real app a short window to send odashboard-ready.
                    this._clearIframeTimers();
                    this._iframeLoadTimer = setTimeout(() => {
                        this._showIframeError();
                    }, IFRAME_POST_LOAD_TIMEOUT);
                };
                iframe.addEventListener("load", this._onIframeLoad);
            }
        });

        // Phase 2: absolute fallback
        this._iframeMaxTimer = setTimeout(() => {
            if (!this._iframeAlive) {
                this._showIframeError();
            }
        }, IFRAME_MAX_TIMEOUT);
    }

    _showIframeError() {
        if (this._iframeAlive || this.state.errorType) return;
        this._clearIframeTimers();
        this.state.iframeSrc = null;
        this.state.errorType = "iframe_error";
    }

    _clearIframeTimers() {
        if (this._iframeLoadTimer) {
            clearTimeout(this._iframeLoadTimer);
            this._iframeLoadTimer = null;
        }
        if (this._iframeMaxTimer) {
            clearTimeout(this._iframeMaxTimer);
            this._iframeMaxTimer = null;
        }
    }

    _cleanupIframeListeners() {
        this._clearIframeTimers();
        if (this._onIframeLoad) {
            const iframe = this.iframeRef.el;
            if (iframe) {
                iframe.removeEventListener("load", this._onIframeLoad);
            }
            this._onIframeLoad = null;
        }
    }

    /**
     * Handle postMessage from the iframe.
     */
    async _onMessage(event) {
        // Only handle messages from our iframe
        const iframe = this.iframeRef.el;
        if (!iframe || event.source !== iframe.contentWindow) {
            return;
        }

        if (!event.data || !event.data.type) {
            return;
        }

        // Any known message from the iframe means it loaded successfully
        if (!this._iframeAlive) {
            this._iframeAlive = true;
            this._cleanupIframeListeners();
        }

        const { type } = event.data;

        // Explicit ready signal — no further action needed
        if (type === "odashboard-ready") {
            return;
        }

        // Open Odoo Settings > ODashboard
        if (type === "odashboard-open-settings") {
            this.onOpenSettings();
            return;
        }

        // Open a URL in a new browser tab (outside the iframe)
        if (type === "odashboard-open-external") {
            const url = event.data.url;
            if (url) {
                window.open(url, "_blank", "noopener,noreferrer");
            }
            return;
        }

        // Reload request (e.g. after logout in iframe)
        if (type === "odashboard-reload") {
            this.state.loading = true;
            await this.loadIframeToken();
            this._startIframeLoadCheck();
            return;
        }

        // Redirect request (e.g. after account linking in iframe auth flow).
        // The iframe sends a URL with a {{return_url}} placeholder (URL-encoded
        // by URLSearchParams as %7B%7Breturn_url%7D%7D) — the parent replaces
        // it with its own location so the auth pages know where to redirect
        // back to after login/register.
        if (type === "odashboard-redirect") {
            let url = event.data.url;
            if (url) {
                url = url.replace(
                    encodeURIComponent("{{return_url}}"),
                    encodeURIComponent(window.location.href),
                );
                window.location.href = url;
            }
            return;
        }

        // Re-authentication request
        if (type === "odashboard-reauth") {
            if (!this._frontendOrigin) {
                console.warn("ODashboard: Cannot respond to reauth — frontend origin unknown");
                return;
            }
            const targetOrigin = this._frontendOrigin;
            try {
                const result = await jsonrpc("/odashboard/iframe-token", {});

                if (result.error || !result.token) {
                    iframe.contentWindow.postMessage({
                        type: "odashboard-reauth-response",
                        error: result.error || "Failed to generate token",
                    }, targetOrigin);
                    return;
                }

                // Inject fresh company IDs on re-auth too
                result.token.company_ids = this._getAllowedCompanyIds();
                const tokenB64 = this._unicodeSafeB64Encode(JSON.stringify(result.token));
                iframe.contentWindow.postMessage({
                    type: "odashboard-reauth-response",
                    token: tokenB64,
                }, targetOrigin);
            } catch (e) {
                console.error("ODashboard: Failed to refresh iframe token", e);
                iframe.contentWindow.postMessage({
                    type: "odashboard-reauth-response",
                    error: "Failed to refresh authentication",
                }, targetOrigin);
            }
            return;
        }

        // Navigation request (open Odoo record/list)
        if (type === "odashboard-navigate") {
            this._handleNavigate(event.data.payload);
        }
    }

    /**
     * Handle navigation requests from the iframe.
     * Opens an Odoo record (form view) or a list view with domain filters.
     *
     * Payload shapes:
     *   { action: "open_record", model: "sale.order", res_id: 42 }
     *   { action: "open_list", model: "sale.order", domain: [...], name: "..." }
     */
    _handleNavigate(payload) {
        if (!payload || !payload.model) return;

        if (payload.action === "open_record" && payload.res_id) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: payload.model,
                res_id: payload.res_id,
                views: [[false, "form"]],
                target: "current",
            });
        } else if (payload.action === "open_list") {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: payload.model,
                name: payload.name || payload.model,
                domain: payload.domain || [],
                views: [[false, "list"], [false, "form"]],
                target: "current",
            });
        }
    }

    /**
     * Get the currently selected company IDs from Odoo's company switcher.
     * Falls back to the cids cookie, then to the current company.
     * @returns {number[]} Array of active company IDs
     */
    _getAllowedCompanyIds() {
        // Primary: use the company service (available in Odoo 18+)
        try {
            const ids = this.companyService.activeCompanyIds;
            if (ids && ids.length) {
                return ids.map(Number);
            }
        } catch {
            // companyService may not be available
        }

        // Fallback: parse the cids cookie (format: "1-3-7")
        const cids = cookie.get("cids");
        if (cids) {
            return cids.split("-").map(Number).filter(Boolean);
        }

        // Last resort: current company only
        try {
            const current = this.companyService.currentCompany;
            if (current && current.id) {
                return [current.id];
            }
        } catch {
            // companyService may not be available
        }

        return [];
    }

    onOpenSettings() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.config.settings",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: { module: "odashboard" },
        });
    }

    /**
     * Base64-encode a string safely, handling Unicode characters.
     * Standard btoa() throws on non-ASCII (e.g. accented names like "Élodie").
     * @param {string} str
     * @returns {string} Base64-encoded string
     */
    _unicodeSafeB64Encode(str) {
        const bytes = new TextEncoder().encode(str);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    onRetry() {
        this.state.loading = true;
        this.state.errorType = null;
        this.state.errorMessage = null;
        this.state.missingFields = [];
        this.state.iframeSrc = null;
        this._iframeAlive = false;
        this._cleanupIframeListeners();
        this.loadIframeToken().then(() => {
            this._startIframeLoadCheck();
        });
    }
}

registry.category("actions").add("odashboard_iframe", ODashboardAction);
