/** @odoo-module **/

import { SettingsFormController } from "@web/webclient/settings_form_view/settings_form_controller";
import { patch } from "@web/core/utils/patch";

patch(SettingsFormController.prototype, {
    /**
     * @override
     * Skip save confirmation dialog for synchronize_key and desynchronize_key actions
     */
    async beforeExecuteActionButton(clickParams) {
        if (clickParams.name === "cancel") {
            return true;
        }
        
        // Skip save dialog for odashboard key synchronization actions
        if (["synchronize_key", "desynchronize_key"].includes(clickParams.name)) {
            return this.model.root.save();
        }
        
        if (
            (await this.model.root.isDirty()) &&
            !["execute"].includes(clickParams.name) &&
            !clickParams.noSaveDialog
        ) {
            return this._confirmSave();
        } else {
            return this.model.root.save();
        }
    }
});
