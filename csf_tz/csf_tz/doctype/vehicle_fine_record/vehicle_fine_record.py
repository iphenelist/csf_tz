# -*- coding: utf-8 -*-
# Copyright (c) 2020, Aakvatech and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
from frappe.model.document import Document
import frappe
from frappe import _
import requests
from requests.exceptions import Timeout
from bs4 import BeautifulSoup
from csf_tz.custom_api import print_out
import re
import json
from time import sleep


class VehicleFineRecord(Document):
    def validate(self):
        """
        Validate the vehicle number plate and get the vehicle name

        1. Check if the vehicle number plate is valid
        2. Get the vehicle name from the vehicle number plate
        3. If the vehicle name is not found, set the vehicle name as the vehicle number plate
        """
        try:
            if self.vehicle:
                vehicle_name = frappe.get_value(
                    "Vehicle", {"number_plate": self.vehicle}, "name"
                )
                if vehicle_name:
                    self.vehicle_doc = vehicle_name
                else:
                    self.vehicle_doc = self.vehicle
        except Exception as e:
            frappe.log_error(
                title=f"Error in VehicleFineRecord.validate",
                message=frappe.get_traceback(),
            )


def check_fine_all_vehicles():
    plate_list = frappe.get_all(
        "Vehicle", fields=["name", "number_plate"], limit_page_length=0
    )
    all_fine_list = []
    for vehicle in plate_list:
        # Limit sending 1 every 5 seconds
        sleep(2)
        fine_list = get_fine(number_plate=vehicle["number_plate"] or vehicle["name"])
        if fine_list and len(fine_list) > 0:
            all_fine_list.extend(fine_list)
    reference_list = frappe.get_all(
        "Vehicle Fine Record",
        filters={"status": ["!=", "PAID"], "reference": ["not in", all_fine_list]},
    )
    for reference in reference_list:
        # Limit sending 1 every 5 seconds
        sleep(2)
        get_fine(reference=reference["name"])


def get_fine(number_plate=None, reference=None):
    if not number_plate and not reference:
        print_out(
            _("Please provide either number plate or reference"),
            alert=True,
            add_traceback=True,
            to_error_log=True,
        )
        return
    # check if the number plate is less than 7 characters
    if number_plate and len(number_plate) < 7:
        print_out(
            f"Please provide a valid number plate for {number_plate}",
            alert=True,
            add_traceback=True,
            to_error_log=True,
        )
        return
    fine_list = []
    token = ""
    url = "https://tms.tpf.go.tz/"

    session = requests.Session()
    try:
        response = session.get(url=url, timeout=30)
    except Timeout:
        frappe.msgprint(_("Error"))
        print("Timeout")
    else:
        print(response.status_code)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            # Find the script tag that contains the AJAX call
            # Regular expression to find the _token value
            token_regex = re.compile(r"_token:\s*'([^']+)'")

            # Searching for the _token pattern
            match = token_regex.search(str(soup))

            # Checking if a match was found and printing the token
            if match:
                token = match.group(1)
            else:
                print("CSRF token not found in the script.")
            if not token:
                print_out(
                    "CSRF token not found in the script.",
                    alert=True,
                    add_traceback=True,
                    to_error_log=True,
                )
                return

            payload = {
                "_token": token,
            }
            if number_plate:
                payload["option"] = "VEHICLE"
                payload["searchable"] = number_plate
            elif reference:
                payload["option"] = "REFERENCE"
                payload["searchable"] = reference
            try:
                # send the payload to the server as a POST request as form data
                response2 = session.post(url=url + "results", data=payload, timeout=5)
            except Timeout:
                frappe.log_error(
                    title="Timeout",
                    message=f"""Timeout for {payload["option"]}: {payload["searchable"]}""",
                )
                response2 = None
            if response2 and response2.status_code == 200:
                if response2.json:
                    data = response2.json().get("dataFromTms")
                    for key, value in data.items():
                        if value.get("reference"):
                            fine_list.append(value["reference"])
                            if frappe.db.exists(
                                "Vehicle Fine Record", value["reference"]
                            ):
                                doc = frappe.get_doc(
                                    "Vehicle Fine Record", value["reference"]
                                )
                                doc.update(value)
                                doc.save()
                            else:
                                fine_doc = frappe.get_doc(
                                    {"doctype": "Vehicle Fine Record", **value}
                                )
                                fine_doc.insert()
                        elif (
                            reference
                            and value.get("1")
                            and "HAIDAIWI" in value["1"].get("status")
                        ):
                            # {"dataFromTms":{"1":{"status":"VEHICLE:T123ABC HAIDAIWI."}}}
                            doc = frappe.get_doc("Vehicle Fine Record", reference)
                            if doc:
                                doc.update({"status": "PAID"})
                                doc.save()
                                frappe.db.commit()
                            else:
                                frappe.log_error(
                                    title="Number plate response exception!",
                                    message=response2,
                                )

                    frappe.db.commit()
        else:
            print_out(response)
    return fine_list
