#!/usr/bin/env python3
"""Patch Panacea's island chat (ChatView.qml) into a single Claude tab.

  - removes the Gemini / ChatGPT / DeepSeek web tabs; the chat always uses
    the API from settings (aiUrl -> local Claude bridge, panacea-claude.service)
  - header: "Claude" + model pills (Opus / Sonnet / Haiku -> settings aiModel)
    + a "new chat" button
  - Enter sends, Shift+Enter inserts a new line
  - English placeholder / empty-state text

Idempotent and all-or-nothing, like lock-patch.py: keeps ChatView.qml.pristine
to upgrade older patch versions; if an anchor is missing (Panacea changed the
file) nothing is written and the stock chat stays. Re-run automatically by
panacea-chat-patch.path whenever ChatView.qml changes (e.g. Panacea updates).
"""
import os
import sys

QML = os.path.expanduser("~/.config/panacea/ChatView.qml")
PRISTINE = QML + ".pristine"
VERSION = "v15"
TAG_PREFIX = "// panacea-local chat patch "
TAG = TAG_PREFIX + VERSION

HEADER = '''        // ''' + TAG + ''': the model switcher (one segmented control) and a new-chat button.
        // No logo or title here: the island's own tab already says Chat, and the
        // pixel Claude marks Claude where it means something (working, asking).
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                implicitWidth: segRow.implicitWidth + 6; implicitHeight: 30; radius: 15
                color: Qt.rgba(1, 1, 1, 0.05)
                Row {
                    id: segRow; anchors.centerIn: parent; spacing: 2
                    Repeater {
                        model: [{id: "opus", name: "Opus"}, {id: "sonnet", name: "Sonnet"}, {id: "haiku", name: "Haiku"}]
                        delegate: Rectangle {
                            id: pill
                            required property var modelData
                            readonly property bool on: (view.sys.cfg.aiModel || "opus") === modelData.id
                            width: pillName.implicitWidth + 24; height: 24; radius: 12
                            color: on ? Qt.rgba(1, 1, 1, 0.14) : (pillMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent")
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Text {
                                id: pillName; anchors.centerIn: parent
                                text: pill.modelData.name
                                color: pill.on ? view.sys.colFg : view.sys.colMuted
                                font { family: view.sys.fontBody; pixelSize: 11; bold: pill.on }
                            }
                            MouseArea {
                                id: pillMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { view.sys.cfg.aiModel = pill.modelData.id; view.sys.saveCfg(); }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: 30; implicitHeight: 30; radius: 15
                color: newMouse.containsMouse && !view.busy ? Qt.rgba(1, 1, 1, 0.1) : "transparent"
                opacity: view.busy ? 0.35 : 1
                Behavior on color { ColorAnimation { duration: 150 } }
                PanaceaClaudeIcon { anchors.centerIn: parent; width: 17; height: 17; kind: "compose"
                                    tint: newMouse.containsMouse ? view.sys.colFg : view.sys.colMuted }
                MouseArea {
                    id: newMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    enabled: !view.busy
                    onClicked: { view.sys.islandChatMessages = []; view.attachments = []; }
                }
            }
        }
'''

ROW_START = '''        Row {
            Layout.alignment: Qt.AlignLeft
            spacing: 4
            Repeater {
                model: [{id:"chat", name:view.sys.tr("Остров")'''
ROW_END = '''        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            visible: view.service !== "chat"'''

LIVE_PROPS = '    property bool busy: false\n    readonly property real boxR: Math.max(10, (sys.cfg.islandRadius > 0 ? sys.cfg.islandRadius : 26) - 15)   // island corner minus its padding\n    // The chat page is rebuilt whenever you come back to it (and when an approval\n    // is answered from the notification, which swaps the page out), and its\n    // request dies with the old page. The bridge keeps working regardless and\n    // records the reply in live.json, so a page only needs to catch up:\n    // still working -> show it; finished -> take the reply that answers our message.\n    property bool ownReq: false          // our own request is still out\n    property string fallbackAnswer: ""   // chat.py\'s answer, used if the bridge left no record\n    function awaiting() { var m = view.sys.islandChatMessages; return m.length > 0 && m[m.length - 1].role === "user"; }\n    function finish(answer, cards) {\n        if (view.awaiting()) { var a = view.sys.islandChatMessages.slice(); a.push({ role: "assistant", content: answer, cards: cards || [] }); view.sys.islandChatMessages = a; }\n        view.busy = false; view.fallbackAnswer = "";\n    }\n    function sync() {\n        var l = view.live || {}, m = view.sys.islandChatMessages;\n        if (!view.awaiting()) { if (!l.busy && !view.ownReq) view.busy = false; return; }\n        var at = m[m.length - 1].at;\n        if (l.busy) { if (!view.ownReq && (!at || l.at === at || l.at === undefined)) view.busy = true; return; }\n        if (l.last && at && l.last.at === at) { view.finish(l.last.answer || "Couldn\'t get a reply.", l.last.cards); return; }\n        if (view.ownReq) return;                       // not recorded yet: our request is still coming\n        if (view.fallbackAnswer) view.finish(view.fallbackAnswer, []);\n        else if (view.busy) view.finish("Couldn\'t get a reply.", []);\n    }\n\n    // live progress + in-chat approval cards, written by bridge.py / approve-mcp.py\n    readonly property string pcDir: Quickshell.env("HOME") + "/.cache/panacea-claude/"\n    readonly property string pcLogo: "file://" + Quickshell.env("HOME") + "/.config/panacea-claude/claude-logo.svg"\n    property var live: ({ busy: false, steps: [] })\n    property var approval: ({})\n    FileView { id: liveFile; path: view.pcDir + "live.json"; printErrors: false\n        onLoaded: { try { view.live = JSON.parse(text()); } catch (e) { return; } view.sync(); } }\n    FileView { id: approvalFile; path: view.pcDir + "approval.json"; printErrors: false\n        onLoaded: { try { view.approval = JSON.parse(text()) || ({}); } catch (e) { view.approval = ({}); } } }\n    Timer { running: true; interval: 1; onTriggered: { liveFile.reload(); approvalFile.reload(); } }   // catch up on open\n    Timer { interval: 350; repeat: true; running: view.busy; triggeredOnStart: true\n        onTriggered: { liveFile.reload(); approvalFile.reload(); } }\n    onBusyChanged: if (!busy) { view.live = ({ busy: false, steps: [] }); view.approval = ({}); }\n    Process { id: answerProc }\n    function answerApproval(choice) {\n        if (!view.approval || !view.approval.id) return;\n        answerProc.command = ["python3", "-I", Quickshell.env("HOME") + "/.local/lib/panacea-claude/approve-mcp.py",\n                              "--answer", String(view.approval.id), choice];\n        answerProc.running = true;\n        view.approval = ({});\n    }\n'
LIVE_BLOCK = '                // what Claude is doing right now, and its approval requests\n                Column {\n                    visible: view.busy\n                    width: parent.width; spacing: 7\n                    // the pixel Claude walks while it works, and waves when it needs you\n                    Row {\n                        spacing: 10\n                        PanaceaClaudeCritter { px: 2; waving: !!(view.approval && view.approval.id); anchors.verticalCenter: parent.verticalCenter }\n                        Text { text: (view.approval && view.approval.id) ? "Waiting for you" : "Working"\n                               anchors.verticalCenter: parent.verticalCenter\n                               color: view.sys.colMuted; font { pixelSize: 12; family: view.sys.fontBody } }\n                    }\n                    Repeater {\n                        // while a card is up, its own step line would only repeat the card\'s reason\n                        model: (view.live.steps || []).filter(function (st, i, all) {\n                            return !(view.approval && view.approval.id && i === all.length - 1 && st.k === "tool"); }).slice(-6)\n                        delegate: Text {\n                            required property var modelData\n                            width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                            maximumLineCount: modelData.k === "text" ? 4 : 3; elide: Text.ElideRight\n                            leftPadding: 0\n                            text: (modelData.k === "tool" ? "›  " : "") + modelData.t   // steps share the reply\'s left edge\n                            color: modelData.k === "text" ? view.sys.colFg : view.sys.colMuted\n                            opacity: modelData.k === "think" ? 0.75 : 1\n                            font { pixelSize: 12; italic: modelData.k === "think" }\n                        }\n                    }\n                    Repeater { model: view.live.cards || []\n                               delegate: PanaceaClaudeCard { sys: view.sys; required property var modelData; card: modelData; width: parent.width } }\n                    Rectangle {\n                        visible: !!(view.approval && view.approval.id)\n                        width: parent.width; height: Math.max(apCol.implicitHeight, apCritter.height) + 28; radius: 14\n                        color: Qt.rgba(1, 1, 1, 0.05); border.color: Qt.rgba(1, 1, 1, 0.14); border.width: 1\n                        PanaceaClaudeCritter { id: apCritter; x: 14; y: 16; px: 3; waving: parent.visible }\n                        Column {\n                            id: apCol; x: apCritter.x + apCritter.width + 14; y: 14; width: parent.width - x - 14; spacing: 9\n                            Text { width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                                   text: "Claude wants to " + String((view.approval && view.approval.title) || "").toLowerCase()\n                                   color: view.sys.colFg; font { pixelSize: 13; bold: true; family: view.sys.fontBody } }\n                            Text { visible: text.length > 0; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                                   text: String((view.approval && view.approval.why) || "")\n                                   color: view.sys.colMuted; font.pixelSize: 12 }\n                            Rectangle {\n                                width: parent.width; height: apBody.implicitHeight + 16; radius: 8\n                                color: Qt.rgba(0, 0, 0, 0.55); border.color: view.sys.colLine; border.width: 1\n                                Text { id: apBody; x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WrapAnywhere\n                                       textFormat: Text.PlainText; maximumLineCount: 10; elide: Text.ElideRight\n                                       text: String((view.approval && view.approval.body) || "")\n                                       color: view.sys.colFg; font { family: view.sys.fontFam; pixelSize: 11 } }\n                            }\n                            Row {\n                                anchors.right: parent.right; spacing: 8\n                                Repeater {\n                                    model: [{ t: "Deny", c: "deny" }, { t: "Allow", c: "allow" }]\n                                    delegate: Rectangle {\n                                        required property var modelData\n                                        width: 86; height: 30; radius: 15\n                                        color: modelData.c === "allow" ? view.sys.colFg\n                                               : (apMa.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.08))\n                                        Text { anchors.centerIn: parent; text: modelData.t\n                                               color: modelData.c === "allow" ? view.sys.colBg : view.sys.colFg\n                                               font { pixelSize: 12; bold: modelData.c === "allow" } }\n                                        MouseArea { id: apMa; anchors.fill: parent; hoverEnabled: true\n                                                    cursorShape: Qt.PointingHandCursor; onClicked: view.answerApproval(modelData.c) }\n                                    }\n                                }\n                            }\n                        }\n                    }\n                }\n'
MASCOT = '        // a little orange pixel Claude, walking in place\n        Item {\n            id: critter\n            anchors.horizontalCenter: parent.horizontalCenter\n            readonly property int px: 6\n            readonly property var body: ["..XXXXXXX..", "..XXXXXXX..", "..XEXXXEX..", "XXXXXXXXXXX",\n                                         "XXXXXXXXXXX", "..XXXXXXX.."]\n            readonly property var legs: [["..X.X.X.X.."], [".X.X.X.X..."]]\n            property int frame: 0\n            property bool blink: false\n            readonly property var rows: body.concat(legs[frame])\n            width: 11 * px; height: rows.length * px + 8\n            Timer { interval: 300; repeat: true; running: critter.visible; onTriggered: critter.frame = 1 - critter.frame }\n            Timer { interval: 3400; repeat: true; running: critter.visible\n                    onTriggered: { critter.blink = true; unblink.restart(); } }\n            Timer { id: unblink; interval: 160; onTriggered: critter.blink = false }\n            Item {\n                id: sprite; width: parent.width; height: critter.rows.length * critter.px\n                SequentialAnimation on y { running: critter.visible; loops: Animation.Infinite\n                    NumberAnimation { from: 4; to: 0; duration: 300; easing.type: Easing.OutQuad }\n                    NumberAnimation { from: 0; to: 4; duration: 300; easing.type: Easing.InQuad } }\n                Repeater {\n                    model: critter.rows.length * 11\n                    delegate: Rectangle {\n                        required property int index\n                        readonly property string ch: critter.rows[Math.floor(index / 11)].charAt(index % 11)\n                        x: (index % 11) * critter.px; y: Math.floor(index / 11) * critter.px\n                        width: critter.px; height: critter.px\n                        visible: ch !== "."\n                        color: ch === "E" && !critter.blink ? "#141414" : "#d97757"\n                    }\n                }\n            }\n        }\n'

# Small QML types used by the patched ChatView, written next to it. (Separate
# files, not inline components: Quickshell 0.3 refused an inline one as a type.)
EXTRA = {
    "PanaceaClaudeIcon.qml": 'import QtQuick\nimport QtQuick.Shapes\n\n// written by chat-patch.py (panacea-claude-bridge)\n// Line icons drawn like Panacea\'s own island tab icons (IslandTabIcon.qml):\n// a 20-unit grid, 1.5 strokes, round caps - crisp at any size.\nItem {\n    id: icon\n    property string kind: "attach"     // attach | send | compose\n    property color tint: "white"\n    property real stroke: 1.6\n    implicitWidth: 18; implicitHeight: 18\n    Shape {\n        width: 20; height: 20\n        scale: Math.min(icon.width, icon.height) / 20\n        transformOrigin: Item.TopLeft\n        antialiasing: true\n        preferredRendererType: Shape.CurveRenderer\n        ShapePath {\n            fillColor: "transparent"; strokeColor: icon.tint; strokeWidth: icon.stroke\n            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin\n            PathSvg { path: icon.kind === "send" ? "M 10 16 L 10 4.5 M 5 9.5 L 10 4.5 L 15 9.5"\n                          : icon.kind === "compose" ? "M 9.5 3.5 L 5.5 3.5 Q 3.5 3.5 3.5 5.5 L 3.5 14.5 Q 3.5 16.5 5.5 16.5 L 14.5 16.5 Q 16.5 16.5 16.5 14.5 L 16.5 10.5 M 14.4 3.4 Q 15.4 2.4 16.4 3.4 L 16.6 3.6 Q 17.6 4.6 16.6 5.6 L 10.6 11.6 L 7.9 12.1 L 8.4 9.4 Z"\n                          : "M 10 4.5 L 10 15.5 M 4.5 10 L 15.5 10" }\n        }\n    }\n}\n',
    "PanaceaClaudeCritter.qml": 'import QtQuick\n\n// written by chat-patch.py (panacea-claude-bridge)\n// the pixel Claude; "waving" is its needs-your-approval animation\nItem {\nproperty var sys\n    id: pc\n    property int px: 3\n    property bool waving: true\n    property int frame: 0\n    property bool blink: false\n    readonly property var frames: [\n        ["..XXXXXXX..", "XXXXXXXXX..", "XXXEXXXEX..", "..XXXXXXXXX", "..XXXXXXXXX", "..XXXXXXX..", "..X.X.X.X.."],\n        ["..XXXXXXX..", "..XXXXXXX..", "..XEXXXEX..", "XXXXXXXXXXX", "XXXXXXXXXXX", "..XXXXXXX..", ".X.X.X.X..."],\n        ["..XXXXXXX..", "..XXXXXXXXX", "..XEXXXEXXX", "XXXXXXXXX..", "XXXXXXXXX..", "..XXXXXXX..", "..X.X.X.X.."],\n        ["..XXXXXXX..", "..XXXXXXX..", "..XEXXXEX..", "XXXXXXXXXXX", "XXXXXXXXXXX", "..XXXXXXX..", "..X.X.X.X.."]]\n    readonly property var rows: pc.waving ? frames[frame] : frames[frame % 2 ? 1 : 3]\n    width: 11 * px; height: 7 * px + 3\n    Timer { interval: 260; repeat: true; running: pc.visible; onTriggered: pc.frame = (pc.frame + 1) % 4 }\n    Timer { interval: 2600; repeat: true; running: pc.visible; onTriggered: { pc.blink = true; pcUnblink.restart(); } }\n    Timer { id: pcUnblink; interval: 150; onTriggered: pc.blink = false }\n    Grid {\n        columns: 11\n        y: pc.waving && pc.frame % 2 === 0 ? 0 : 3\n        Behavior on y { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }\n        Repeater {\n            model: 77\n            Rectangle {\n                required property int index\n                readonly property string ch: pc.rows[Math.floor(index / 11)].charAt(index % 11)\n                width: pc.px; height: pc.px\n                color: ch === "." ? "transparent" : ch === "E" && !pc.blink ? "#141414" : "#d97757"\n            }\n        }\n    }\n}\n\n',
    "PanaceaClaudeCard.qml": 'import QtQuick\n\n// written by chat-patch.py (panacea-claude-bridge)\n// a finished approval: what ran, and whether it worked\nRectangle {\n    property var sys\n    id: cr\n    property var card: ({})\n    readonly property string outcome: cr.card.decision === "allow" ? (cr.card.ok ? "done" : "failed")\n                                    : cr.card.decision === "deny" ? "denied" : "unanswered"\n    height: crRow.implicitHeight + 18; radius: 12\n    color: Qt.rgba(1, 1, 1, 0.04); border.color: sys.colLine; border.width: 1\n    Row {\n        id: crRow; x: 12; y: 9; width: parent.width - 24; spacing: 10\n        Rectangle {\n            width: 18; height: 18; radius: 9; anchors.verticalCenter: parent.verticalCenter\n            color: cr.outcome === "done" ? sys.colFg : cr.outcome === "failed" ? sys.colCrit : Qt.rgba(1, 1, 1, 0.1)\n            Text { anchors.centerIn: parent; text: cr.outcome === "done" ? "✓" : cr.outcome === "failed" ? "!" : "×"\n                   color: cr.outcome === "done" ? sys.colBg : cr.outcome === "failed" ? "#ffffff" : sys.colMuted\n                   font { pixelSize: 11; bold: true } }\n        }\n        Column {\n            width: parent.width - 28 - crState.implicitWidth - 10; spacing: 2; anchors.verticalCenter: parent.verticalCenter\n            Text { width: parent.width; elide: Text.ElideRight; text: String(cr.card.title || "")\n                   color: sys.colFg; font { pixelSize: 12; bold: true; family: sys.fontBody } }\n            Text { width: parent.width; elide: Text.ElideRight; maximumLineCount: 1; textFormat: Text.PlainText\n                   visible: text.length > 0; text: String(cr.card.body || "").replace(/\\s*\\n\\s*/g, " ")\n                   color: sys.colMuted; font { family: sys.fontFam; pixelSize: 11 } }\n        }\n        Text { id: crState; anchors.verticalCenter: parent.verticalCenter\n               text: ({ done: "Done", failed: "Failed", denied: "Denied", unanswered: "No answer" })[cr.outcome]\n               color: cr.outcome === "failed" ? sys.colCrit : sys.colMuted; font.pixelSize: 11 }\n    }\n}\n',
}

REPLACEMENTS = [
    ('    ColumnLayout {\n        anchors.fill: parent\n        spacing: 10\n', "    ColumnLayout {\n        anchors.fill: parent\n        // the island gives a page 20 px below it but 15 px at the sides; the message\n        // box sits 15 px from the bottom too, so its corners run parallel to the island's\n        anchors.bottomMargin: -5\n        spacing: 10\n"),
    # the message box: concentric corners, no outline, line icons
    ('            radius: height / 2\n            color: Qt.rgba(1, 1, 1, 0.07)\n            border.width: 1\n            border.color: input.activeFocus ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.07)\n', '            // concentric with the island: its corner radius minus the 15 px the content sits inside it.\n            // No outline; focus only lifts the fill a touch.\n            radius: view.boxR\n            color: input.activeFocus ? Qt.rgba(1, 1, 1, 0.075) : Qt.rgba(1, 1, 1, 0.055)\n            Behavior on color { ColorAnimation { duration: 150 } }\n'),
    ('                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 18\n                    color: attachMouse.containsMouse ? Qt.rgba(1,1,1,0.16) : Qt.rgba(1,1,1,0.07)\n                    Glyph { anchors.centerIn: parent; glyph: String.fromCodePoint(0xF03E2); fontFam: view.sys.fontFam; size: 19; color: view.sys.colFg }\n', '                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: view.boxR - 6\n                    color: attachMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"\n                    Behavior on color { ColorAnimation { duration: 150 } }\n                    PanaceaClaudeIcon { anchors.centerIn: parent; width: 18; height: 18; kind: "attach"\n                                        tint: attachMouse.containsMouse ? view.sys.colFg : view.sys.colMuted }\n'),
    ('                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 18\n                    color: !view.busy && (input.text.trim().length || view.attachments.length) ? view.sys.colFg : Qt.rgba(1,1,1,0.09)\n                    Text { anchors.centerIn: parent; text: "↑"; color: !view.busy && (input.text.trim().length || view.attachments.length) ? view.sys.colBg : view.sys.colMuted; font { pixelSize: 21; bold: true } }\n', '                    readonly property bool ready: !view.busy && (input.text.trim().length || view.attachments.length) > 0\n                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: view.boxR - 6\n                    color: ready ? view.sys.colFg : Qt.rgba(1, 1, 1, 0.06)\n                    Behavior on color { ColorAnimation { duration: 150 } }\n                    PanaceaClaudeIcon { anchors.centerIn: parent; width: 17; height: 17; kind: "send"; stroke: 1.9\n                                        tint: parent.ready ? view.sys.colBg : view.sys.colMuted }\n'),
    # the message box shares the left/right edges of the header, messages and cards
    ('            Layout.leftMargin: 8; Layout.rightMargin: 8\n', '            Layout.leftMargin: 0; Layout.rightMargin: 0\n'),
    ("width: scroll.availableWidth; spacing: 10", "width: scroll.availableWidth; spacing: 16"),
    ("""                Repeater {
                    model: view.sys.islandChatMessages
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width; height: message.implicitHeight + 20; radius: 12
                        color: modelData.role === "user" ? Qt.rgba(1,1,1,0.1) : Qt.rgba(1,1,1,0.04)
                        Text { id: message; x: 10; y: 10; width: parent.width - 20; text: modelData.content; color: view.sys.colFg; wrapMode: Text.Wrap; textFormat: Text.PlainText; font.pixelSize: 13 }
                    }
                }
""", """                Repeater {
                    model: view.sys.islandChatMessages
                    delegate: Column {
                        id: msgItem
                        required property var modelData
                        readonly property bool mine: modelData.role === "user"
                        width: parent.width; spacing: 8
                        // what Claude ran with your approval, and how it went
                        Repeater { model: msgItem.modelData.cards || []
                                   delegate: PanaceaClaudeCard { sys: view.sys; required property var modelData; card: modelData; width: msgItem.width } }
                        // yours: a bubble on the right; Claude's: plain text across the width
                        Rectangle {
                            visible: String(msgItem.modelData.content || "").length > 0
                            anchors.right: msgItem.mine ? parent.right : undefined
                            width: msgItem.mine ? message.width + 28 : parent.width
                            height: message.implicitHeight + (msgItem.mine ? 20 : 0)
                            radius: 16
                            color: msgItem.mine ? Qt.rgba(1, 1, 1, 0.1) : "transparent"
                            Text { id: message
                                   x: msgItem.mine ? 14 : 0; y: msgItem.mine ? 10 : 0
                                   width: msgItem.mine ? Math.min(implicitWidth, msgItem.width * 0.78 - 28) : parent.width
                                   text: msgItem.modelData.content; color: view.sys.colFg; wrapMode: Text.Wrap
                                   textFormat: Text.PlainText; font.pixelSize: 13; lineHeight: 1.15 }
                        }
                    }
                }
"""),
    ("""        attachments = []; input.text = ""; busy = true;
""", """        attachments = []; input.text = ""; busy = true; ownReq = true; fallbackAnswer = "";
"""),
    ("""                    var result = JSON.parse(text);
                    var arr = view.sys.islandChatMessages.slice();
                    arr.push({role: "assistant", content: result.answer || ("Ошибка: " + result.error)});
                    view.sys.islandChatMessages = arr;
                } catch (e) {
                    var arr2 = view.sys.islandChatMessages.slice();
                    arr2.push({role:"assistant", content:"Не удалось получить ответ."});
                    view.sys.islandChatMessages = arr2;
                }
                view.busy = false;
""", """                    var result = JSON.parse(text);
                    view.fallbackAnswer = result.answer || ("Error: " + result.error);
                } catch (e) {}
                // the bridge's record of this reply (with its done/failed/denied cards) wins;
                // chat.py's answer is only the fallback
                view.ownReq = false; Qt.callLater(liveFile.reload);
"""),
    ("""        a.push({role:"user", content:msg}); sys.islandChatMessages = a;""", """        a.push({role:"user", content:msg, at:Date.now()}); sys.islandChatMessages = a;   // "at": the bridge tags its reply with it"""),
    # Super+C: the message box has focus as soon as the chat opens. The shell
    # gives focus to the loaded view (again 60 ms after opening); a plain Item
    # root kept it for itself, a FocusScope passes it on to the input.
    ("Item {\n    id: view\n", "FocusScope {   " + TAG + "\n    id: view\n"),
    ("id: input; width: inputScroll.width;", "id: input; focus: true; width: inputScroll.width;"),
    # Ctrl+N: new chat, like the + button
    ("if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_V) {",
     "if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_N) { if (!view.busy) { view.sys.islandChatMessages = []; view.attachments = []; input.text = \"\"; } event.accepted = true; }\n"
     "                                else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_V) {"),
    # no "agent event" cards in the chat: Panacea copies every notification
    # mentioning Claude/Codex into the chat tab (Claude desktop's session
    # status updates piled up there and could not be dismissed)
    # live progress, approval cards, logo and the pixel Claude (bridge.py / approve-mcp.py)
    ("    property bool busy: false\n", LIVE_PROPS),
    ('                Text { visible: view.busy; text: view.sys.tr("Думаю…"); color: view.sys.colMuted }\n', LIVE_BLOCK),
    ('        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "✦"; color: view.sys.colFg; font.pixelSize: 28 }\n', MASCOT),
    ("    readonly property var visibleEvents: sys.islandAgentEvents.filter(e =>\n",
     "    readonly property var visibleEvents: [].filter(e =>   " + TAG + "\n"),
    # always the API chat, never the web tabs
    ("    property string service: sys.islandChatService\n",
     "    property string service: \"chat\"   " + TAG + "\n"
     "    Component.onCompleted: {\n"
     "        sys.islandChatService = \"chat\";\n"
     "        // coming back from the island file picker (portal-patch in panacea-config):\n"
     "        // restore the draft and attachments, plus the files just picked\n"
     "        if (sys.pendingChatAttach && sys.pendingChatAttach.length) {\n"
     "            view.attachments = sys.pendingChatAttach; sys.pendingChatAttach = [];\n"
     "        }\n"
     "        if (sys.chatDraft) { input.text = sys.chatDraft; sys.chatDraft = \"\"; }\n"
     "        Qt.callLater(function () { input.forceActiveFocus(); input.cursorPosition = input.length; });   // type right away\n"
     "    }\n"
     "    Component.onDestruction: {\n"
     "        if (sys.chatDraft !== undefined) sys.chatDraft = input.text;\n"
     "        if (sys.pendingChatAttach !== undefined) sys.pendingChatAttach = view.attachments.slice();\n"
     "    }\n"),
    # Enter sends, Shift+Enter = new line (Ctrl+Enter still sends)
    ("else if ((event.modifiers & Qt.ControlModifier) && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) { view.send(); event.accepted = true; }",
     "else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier)) { view.send(); event.accepted = true; }"),
    ('text: view.sys.tr("Сообщение…")', 'text: "Message Claude…"'),
    ('text: view.sys.tr("Спросите что угодно")', 'text: "Ask Claude anything"'),
    ('text: view.sys.tr("Добавьте адрес API, модель и ключ в настройках лаунчера.")',
     'text: "Enter to send · Shift+Enter for a new line"'),
]


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write_atomic(p, text):
    # In place, not tmp + rename: Quickshell's file watcher loses a file that is
    # swapped for a new one, and then never reloads the shell.
    with open(p, "r+" if os.path.exists(p) else "w", encoding="utf-8") as f:
        f.seek(0)
        f.write(text)
        f.truncate()


CHAT_PY = os.path.expanduser("~/.config/panacea/scripts/chat.py")
CHAT_PY_OLD = "urlopen(req,timeout=90)"
CHAT_PY_NEW = "urlopen(req,timeout=600)"   # room for approval cards (no inline comment: mid-line)
CHAT_PY_BROKEN = "urlopen(req,timeout=600)  # panacea-claude: room for approval cards"   # chat-patch v4 bug


def patch_chat_py():
    """The chat script gives up after 90 s; Claude may wait on approval cards."""
    try:
        s = read(CHAT_PY)
    except OSError:
        return
    if CHAT_PY_BROKEN in s:
        s = s.replace(CHAT_PY_BROKEN, CHAT_PY_OLD)
        write_atomic(CHAT_PY, s)
        os.chmod(CHAT_PY, 0o755)
    if CHAT_PY_NEW in s:
        return
    if s.count(CHAT_PY_OLD) != 1:
        print("chat-patch: chat.py timeout anchor not found - long tasks may time out", file=sys.stderr)
        return
    write_atomic(CHAT_PY, s.replace(CHAT_PY_OLD, CHAT_PY_NEW))
    os.chmod(CHAT_PY, 0o755)


def main() -> int:
    patch_chat_py()
    try:
        cur = read(QML)
    except OSError as e:
        print(f"chat-patch: cannot read {QML}: {e}", file=sys.stderr)
        return 1
    for name, text in EXTRA.items():                 # the helper types, kept current
        path = os.path.join(os.path.dirname(QML), name)
        try:
            same = read(path) == text
        except OSError:
            same = False
        if not same:
            write_atomic(path, text)
    if TAG in cur:
        return 0
    if TAG_PREFIX in cur:
        if not os.path.exists(PRISTINE):
            print("chat-patch: older patch but no pristine copy - leaving as is", file=sys.stderr)
            return 2
        src = read(PRISTINE)
    else:
        src = cur

    out = src
    a, b = out.find(ROW_START), out.find(ROW_END)
    if out.count(ROW_START) != 1 or out.count(ROW_END) != 1 or not 0 <= a < b:
        print("chat-patch: tab row anchor not found (Panacea changed ChatView.qml?) - untouched", file=sys.stderr)
        return 2
    out = out[:a] + HEADER + out[b:]
    for old, new in REPLACEMENTS:
        if out.count(old) != 1:
            print(f"chat-patch: anchor not found: {old[:50]!r} - untouched", file=sys.stderr)
            return 2
        out = out.replace(old, new, 1)

    if TAG_PREFIX not in src:
        write_atomic(PRISTINE, src)
    write_atomic(QML, out)
    print(f"chat-patch: applied {VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
