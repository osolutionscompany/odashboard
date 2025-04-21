/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class OdashboardIframeWidget extends Component {
  setup() {
    // Retrieve the URL from the record's data to use as the iframe's src
    this.iframeSrc = this.props.record.data.connection_url || "";

    // Get the necessary services for navigation
    this.actionService = useService("action");
    this.orm = useService("orm");

    // Method to handle messages from iframe
    this.handleMessage = this.handleMessage.bind(this);

    // Add event listener when component is mounted
    onMounted(() => {
      window.addEventListener("message", this.handleMessage, false);
    });

    // Remove event listener when component is unmounted
    onWillUnmount(() => {
      window.removeEventListener("message", this.handleMessage, false);
    });
  }

  /**
   * Handle messages received from the iframe
   * @param {MessageEvent} event - The message event
   */
  handleMessage(event) {
    // Basic security check to validate message origin if needed
    // if (event.origin !== 'https://trusted-source.com') return;

    const message = event.data;

    // Process the message if it has the expected format
    if (message && typeof message === "object") {
      console.log("Received message from iframe:", message);

      // Handle navigation request
      if (message.type === "navigate") {
        this.handleNavigation(message);
      }
    }
  }

  /**
   * Handle navigation requests from iframe
   * @param {Object} message - The navigation message
   */
  handleNavigation(message) {
    if (!message.model) {
      console.error("Navigation request missing model");
      return;
    }

    // Default action is to open a list view
    const action = {
      type: "ir.actions.act_window",
      res_model: message.model,
      views: [
        [false, "list"],
        [false, "form"],
      ],
      target: message.target || "current",
      name: message.name || message.model,
    };

    // If domain is provided, add it to the action
    if (message.domain) {
      action.domain = message.domain;
    }

    // If record ID is provided, open form view instead
    if (message.res_id) {
      action.res_id = message.res_id;
      action.views = [[false, "form"]];
    }

    // Execute the action
    this.actionService.doAction(action);
  }
}
OdashboardIframeWidget.template = "OdashboardIframeWidgetTemplate";

export const OdashboardIframeWidgetDef = {
  component: OdashboardIframeWidget,
};

// Register the widget in the view_widgets registry
registry
  .category("view_widgets")
  .add("odashboard_iframe_widget", OdashboardIframeWidgetDef);
