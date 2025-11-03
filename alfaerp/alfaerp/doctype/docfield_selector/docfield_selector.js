// Copyright (c) 2025, roshan ramani and contributors
// For license information, please see license.txt

frappe.ui.form.on("DocField Selector", {
	refresh(frm) {

	},

	doc_type: function (frm) {
		if (frm.doc.doc_type) {
			// Clear existing fields
			frm.clear_table("fields");

			// Fetch fields from the selected DocType
			frappe.call({
				method: "frappe.client.get",
				args: {
					doctype: "DocType",
					name: frm.doc.doc_type,
				},
				callback: function (r) {
					if (r.message && r.message.fields) {
						// Store fields metadata for later use
						frm.doctype_fields_meta = r.message.fields;
						
						// Populate fields in the child table
						r.message.fields.forEach(function (field) {
                            let row = frm.add_child("fields");
                            row.label = field.label;
                            row.fieldtype = field.fieldtype;
                            row.fieldname = field.fieldname;
                            
                            // If field is mandatory, check and make readonly
                            if (field.reqd) {
                                row.is_visible_in_mobile = 1;
                            } else {
                                row.is_visible_in_mobile = 0;
                            }
						});
						frm.refresh_field("fields");
					}
				},
			});
		}
	},

	onload: function (frm) {
		$(frm.wrapper).on("grid-row-render", function (e, grid_row) {
			// Make is_visible_in_mobile readonly for mandatory fields
			if (grid_row.doc && grid_row.doc.fieldname && frm.doctype_fields_meta) {
				let field_data = frm.doctype_fields_meta.find(f => f.fieldname === grid_row.doc.fieldname);
				if (field_data && field_data.reqd) {
					grid_row.doc.is_visible_in_mobile = 1;
					if (grid_row.grid.grid_form && grid_row.grid.grid_form.fields_dict.is_visible_in_mobile) {
						grid_row.grid.grid_form.fields_dict.is_visible_in_mobile.df.read_only = 1;
						grid_row.grid.grid_form.fields_dict.is_visible_in_mobile.refresh();
					}
				}
			}
		});
	},
});
