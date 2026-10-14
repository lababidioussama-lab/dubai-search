#!/usr/bin/env python3
"""Generate an unsigned iOS Shortcut that saves videos from any link, without watermark.

Usage:  python3 build_shortcut.py https://your-cobalt-server.example/ [API_KEY]
        -> writes SaveVideo.shortcut
Then on a Mac:  shortcuts sign -m anyone -i SaveVideo.shortcut -o SaveVideo-signed.shortcut
(iOS refuses to import unsigned shortcut files; see README.md for building it by hand instead.)

Flow: link from share sheet / clipboard
  -> TikTok links: tikwm.com (works without your own server)
  -> everything else: your cobalt server (status redirect/tunnel -> url, picker -> every item's url)
  -> download every link and save it to Photos.
"""
import plistlib
import sys
import uuid

TIKWM_URL = "https://www.tikwm.com/api/"
LINKS = "Links"


def new_uuid():
    return str(uuid.uuid4()).upper()


def action(identifier, params=None, uid=None):
    p = dict(params or {})
    if uid:
        p["UUID"] = uid
    return {"WFWorkflowActionIdentifier": identifier, "WFWorkflowActionParameters": p}


def out(uid, name):
    return {"OutputUUID": uid, "Type": "ActionOutput", "OutputName": name}


def var(name):
    return {"Type": "Variable", "VariableName": name}


def attachment(ref):
    """A whole-parameter reference to an action output or variable."""
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def text(s, *refs):
    """A text field; each U+FFFC in s is replaced by the matching ref."""
    ranges, i = {}, 0
    for pos, ch in enumerate(s):
        if ch == "￼":
            ranges["{%d, 1}" % pos] = refs[i]
            i += 1
    value = {"string": s}
    if ranges:
        value["attachmentsByRange"] = ranges
    return {"Value": value, "WFSerializationType": "WFTextTokenString"}


def dict_field(items):
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": text(k), "WFValue": v} for k, v in items
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def if_block(input_ref, condition, value, then_actions, else_actions):
    gid = new_uuid()
    start = action("is.workflow.actions.conditional", {
        "GroupingIdentifier": gid,
        "WFControlFlowMode": 0,
        "WFCondition": condition,  # 4 = is, 99 = contains
        "WFConditionalActionString": value,
        "WFInput": {"Type": "Variable", "Variable": attachment(input_ref)},
    })
    otherwise = action("is.workflow.actions.conditional",
                       {"GroupingIdentifier": gid, "WFControlFlowMode": 1})
    end = action("is.workflow.actions.conditional",
                 {"GroupingIdentifier": gid, "WFControlFlowMode": 2}, new_uuid())
    return [start, *then_actions, otherwise, *else_actions, end]


def repeat_each(input_ref, body):
    gid = new_uuid()
    return [
        action("is.workflow.actions.repeat.each", {
            "GroupingIdentifier": gid, "WFControlFlowMode": 0, "WFInput": attachment(input_ref),
        }),
        *body,
        action("is.workflow.actions.repeat.each",
               {"GroupingIdentifier": gid, "WFControlFlowMode": 2}, new_uuid()),
    ]


def get_value(key, input_ref, uid):
    return action("is.workflow.actions.getvalueforkey", {
        "WFGetDictionaryValueType": "Value",
        "WFDictionaryKey": key,
        "WFInput": attachment(input_ref),
    }, uid)


def add_to_links(ref):
    return action("is.workflow.actions.appendvariable",
                  {"WFVariableName": LINKS, "WFInput": attachment(ref)})


def build(server, api_key=""):
    ids = {k: new_uuid() for k in (
        "server", "match", "link", "tikwm", "tikwm_url",
        "cobalt", "status", "picker", "picker_url", "cobalt_url", "file")}
    link = out(ids["link"], "Item from List")

    headers = [("Accept", text("application/json")),
               ("Content-Type", text("application/json"))]
    if api_key:
        headers.append(("Authorization", text("Api-Key " + api_key)))

    tiktok = [
        action("is.workflow.actions.downloadurl", {
            "WFURL": TIKWM_URL,
            "WFHTTPMethod": "POST",
            "WFHTTPBodyType": "Form",
            "WFFormValues": dict_field([("url", text("￼", link)), ("hd", text("1"))]),
        }, ids["tikwm"]),
        get_value("data.play", out(ids["tikwm"], "Contents of URL"), ids["tikwm_url"]),
        add_to_links(out(ids["tikwm_url"], "Dictionary Value")),
    ]

    cobalt_resp = out(ids["cobalt"], "Contents of URL")
    everything_else = [
        action("is.workflow.actions.downloadurl", {
            "WFURL": text("￼", out(ids["server"], "Text")),
            "WFHTTPMethod": "POST",
            "ShowHeaders": True,
            "WFHTTPHeaders": dict_field(headers),
            "WFHTTPBodyType": "JSON",
            "WFJSONValues": dict_field([
                ("url", text("￼", link)),
                ("videoQuality", text("1080")),
            ]),
        }, ids["cobalt"]),
        get_value("status", cobalt_resp, ids["status"]),
        *if_block(out(ids["status"], "Dictionary Value"), 4, "picker",
                  [get_value("picker", cobalt_resp, ids["picker"]),
                   *repeat_each(out(ids["picker"], "Dictionary Value"), [
                       get_value("url", var("Repeat Item"), ids["picker_url"]),
                       add_to_links(out(ids["picker_url"], "Dictionary Value")),
                   ])],
                  [get_value("url", cobalt_resp, ids["cobalt_url"]),
                   add_to_links(out(ids["cobalt_url"], "Dictionary Value"))]),
    ]

    actions = [
        # Your server address — the only thing to change.
        action("is.workflow.actions.gettext",
               {"WFTextActionText": text(server)}, ids["server"]),
        # Find the link in whatever was shared (or the clipboard).
        action("is.workflow.actions.text.match", {
            "WFMatchTextPattern": r"https?://\S+",
            "WFMatchTextCaseSensitive": False,
            "text": attachment({"Type": "ExtensionInput"}),
        }, ids["match"]),
        action("is.workflow.actions.getitemfromlist", {
            "WFItemSpecifier": "First Item",
            "WFInput": attachment(out(ids["match"], "Matches")),
        }, ids["link"]),
        *if_block(link, 99, "tiktok.com", tiktok, everything_else),
        # Download every link and save it.
        *repeat_each(var(LINKS), [
            action("is.workflow.actions.downloadurl",
                   {"WFURL": text("￼", var("Repeat Item"))}, ids["file"]),
            action("is.workflow.actions.savetocameraroll",
                   {"WFInput": attachment(out(ids["file"], "Contents of URL"))}),
        ]),
        action("is.workflow.actions.notification", {
            "WFNotificationActionTitle": "Saved",
            "WFNotificationActionBody": "Saved to Photos",
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
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open("SaveVideo.shortcut", "wb") as f:
        plistlib.dump(build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""), f,
                      fmt=plistlib.FMT_BINARY)
    print("Wrote SaveVideo.shortcut (unsigned)")
