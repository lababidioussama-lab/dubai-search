#!/usr/bin/env python3
"""Generate an unsigned iOS Shortcut that saves TikTok videos without a watermark.

Usage:  python3 build_shortcut.py            -> writes SaveTikTok.shortcut
Then on a Mac:  shortcuts sign -m anyone -i SaveTikTok.shortcut -o SaveTikTok-signed.shortcut
(iOS refuses to import unsigned shortcut files; see README.md for building it by hand instead.)
"""
import plistlib
import uuid

API_URL = "https://www.tikwm.com/api/"


def new_uuid():
    return str(uuid.uuid4()).upper()


def action(identifier, params=None, uid=None):
    p = dict(params or {})
    if uid:
        p["UUID"] = uid
    return {"WFWorkflowActionIdentifier": identifier, "WFWorkflowActionParameters": p}


def output_ref(uid, name):
    """A whole-parameter reference to another action's output."""
    return {
        "Value": {"OutputUUID": uid, "Type": "ActionOutput", "OutputName": name},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def text_with(uid, name):
    """A text field containing only another action's output."""
    return {
        "Value": {
            "string": "￼",
            "attachmentsByRange": {
                "{0, 1}": {"OutputUUID": uid, "Type": "ActionOutput", "OutputName": name}
            },
        },
        "WFSerializationType": "WFTextTokenString",
    }


def plain_text(s):
    return {"Value": {"string": s}, "WFSerializationType": "WFTextTokenString"}


def dict_field(items):
    """WFDictionaryFieldValue from (key, value-token-string) pairs."""
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": plain_text(k), "WFValue": v} for k, v in items
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def build():
    match_id, first_id, api_id, video_url_id, video_id = (new_uuid() for _ in range(5))
    actions = [
        # 1. Find the link in whatever was shared (or the clipboard).
        action("is.workflow.actions.text.match", {
            "WFMatchTextPattern": r"https?://\S+",
            "WFMatchTextCaseSensitive": False,
            "text": {
                "Value": {"Type": "ExtensionInput"},
                "WFSerializationType": "WFTextTokenAttachment",
            },
        }, match_id),
        action("is.workflow.actions.getitemfromlist", {
            "WFItemSpecifier": "First Item",
            "WFInput": output_ref(match_id, "Matches"),
        }, first_id),
        # 2. Ask the resolver API for the no-watermark video URL.
        action("is.workflow.actions.downloadurl", {
            "WFURL": API_URL,
            "WFHTTPMethod": "POST",
            "WFHTTPBodyType": "Form",
            "WFFormValues": dict_field([
                ("url", text_with(first_id, "Item from List")),
                ("hd", plain_text("1")),
            ]),
            "ShowHeaders": False,
        }, api_id),
        action("is.workflow.actions.getvalueforkey", {
            "WFGetDictionaryValueType": "Value",
            "WFDictionaryKey": "data.play",
            "WFInput": output_ref(api_id, "Contents of URL"),
        }, video_url_id),
        # 3. Download the MP4 and save it to Photos.
        action("is.workflow.actions.downloadurl", {
            "WFURL": text_with(video_url_id, "Dictionary Value"),
        }, video_id),
        action("is.workflow.actions.savetocameraroll", {
            "WFInput": output_ref(video_id, "Contents of URL"),
        }),
        action("is.workflow.actions.notification", {
            "WFNotificationActionTitle": "Saved",
            "WFNotificationActionBody": "Video saved to Photos",
        }),
    ]
    return {
        "WFWorkflowClientVersion": "2302.0.4",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4282601983,
            "WFWorkflowIconGlyphNumber": 61440,
        },
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem"],
        "WFWorkflowNoInputBehavior": {
            "Name": "WFWorkflowNoInputBehaviorGetClipboard",
            "Parameters": {},
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowActions": actions,
    }


if __name__ == "__main__":
    with open("SaveTikTok.shortcut", "wb") as f:
        plistlib.dump(build(), f, fmt=plistlib.FMT_BINARY)
    print("Wrote SaveTikTok.shortcut (unsigned)")
