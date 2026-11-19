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
VERSION = "v23"
TAG_PREFIX = "// panacea-local chat patch "
TAG = TAG_PREFIX + VERSION

HEADER = '''        // ''' + TAG + ''': the model switcher (one segmented control) and a new-chat button.
        // No logo or title here: the island's own tab already says Chat, and the
        // pixel Claude marks Claude where it means something (working, asking).
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                id: segBox
                implicitWidth: segRow.implicitWidth + 6; implicitHeight: 30; radius: height / 2
                color: Qt.rgba(1, 1, 1, 0.05)
                // one pill slides (and stretches) behind the names instead of each name lighting up
                property Item active: null
                Rectangle {
                    visible: segBox.active !== null
                    y: (segBox.height - height) / 2; height: 24; radius: 12
                    x: segBox.active ? segRow.x + segBox.active.x : 3
                    width: segBox.active ? segBox.active.width : 0
                    color: Qt.rgba(1, 1, 1, 0.14)
                    Behavior on x { NumberAnimation { duration: 340; easing.type: Easing.OutBack; easing.overshoot: 0.9 } }
                    Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                }
                Row {
                    id: segRow; anchors.centerIn: parent; spacing: 2
                    Repeater {
                        model: [{id: "opus", name: "Opus"}, {id: "sonnet", name: "Sonnet"}, {id: "haiku", name: "Haiku"}]
                        delegate: Rectangle {
                            id: pill
                            required property var modelData
                            readonly property bool on: (view.sys.cfg.aiModel || "opus") === modelData.id
                            width: pillName.implicitWidth + 24; height: 24; radius: height / 2
                            color: "transparent"   // hover only lights the name; the sliding pill is the one highlight
                            onOnChanged: if (on) segBox.active = pill
                            Component.onCompleted: if (on) segBox.active = pill
                            Behavior on color { ColorAnimation { duration: 150 } }
                            Text {
                                id: pillName; anchors.centerIn: parent
                                text: pill.modelData.name
                                color: pill.on || pillMouse.containsMouse ? view.sys.colFg : view.sys.colMuted
                                Behavior on color { ColorAnimation { duration: 200 } }
                                scale: pillMouse.pressed ? 0.92 : 1
                                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                                font { family: view.sys.fontBody; pixelSize: 11; bold: true }
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
                implicitWidth: 30; implicitHeight: 30; radius: height / 2
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

LIVE_PROPS = '    property bool busy: false\n    // One radius system, taken from the island\'s corner so the curves echo it:\n    // surfaces (message box, cards, bubbles) boxR, controls inside them rInner,\n    // small controls (model switcher, new chat) fully round.\n    readonly property real islandR: sys.cfg.islandRadius > 0 ? sys.cfg.islandRadius : 26\n    readonly property real boxR: Math.max(14, islandR - 6)\n    readonly property real rInner: Math.max(8, boxR - 6)\n    // what the pixel Claude above the steps is doing: a card is up, a tool runs, or it thinks\n    readonly property string statusMood: (approval && approval.id) ? "waiting" : answered.tuid !== undefined ? "working"\n        : ((live.steps || []).length && live.steps[live.steps.length - 1].k === "tool") ? "working" : "thinking"\n    // The chat page is rebuilt whenever you come back to it (and when an approval\n    // is answered from the notification, which swaps the page out), and its\n    // request dies with the old page. The bridge keeps working regardless and\n    // records the reply in live.json, so a page only needs to catch up:\n    // still working -> show it; finished -> take the reply that answers our message.\n    property bool ownReq: false          // our own request is still out\n    property string fallbackAnswer: ""   // chat.py\'s answer, used if the bridge left no record\n    function awaiting() { var m = view.sys.islandChatMessages; return m.length > 0 && m[m.length - 1].role === "user"; }\n    function finish(answer, cards, timeline) {\n        if (view.awaiting()) { var a = view.sys.islandChatMessages.slice(); a.push({ role: "assistant", content: answer, cards: cards || [], timeline: timeline || [] }); view.sys.islandChatMessages = a; }\n        view.busy = false; view.fallbackAnswer = "";\n    }\n    function sync() {\n        var l = view.live || {}, m = view.sys.islandChatMessages;\n        if (!view.awaiting()) { if (!l.busy && !view.ownReq) view.busy = false; return; }\n        var at = m[m.length - 1].at;\n        if (l.busy) { if (!view.ownReq && (!at || l.at === at || l.at === undefined)) view.busy = true; return; }\n        if (l.last && at && l.last.at === at) { view.finish(l.last.answer || "Couldn\'t get a reply.", l.last.cards, l.last.timeline); return; }\n        if (view.ownReq) return;                       // not recorded yet: our request is still coming\n        if (view.fallbackAnswer) view.finish(view.fallbackAnswer, []);\n        else if (view.busy) view.finish("Couldn\'t get a reply.", []);\n    }\n\n    // live progress + in-chat approval cards, written by bridge.py / approve-mcp.py\n    readonly property string pcDir: Quickshell.env("HOME") + "/.cache/panacea-claude/"\n    readonly property string pcLogo: "file://" + Quickshell.env("HOME") + "/.config/panacea-claude/claude-logo.svg"\n    property var live: ({ busy: false, steps: [] })\n    property var approval: ({})\n    // polled while busy; only a real change touches the view (re-setting the same state\n    // every 350 ms rebuilt the steps and made them blink)\n    property string liveText: ""\n    property string approvalText: ""\n    FileView { id: liveFile; path: view.pcDir + "live.json"; printErrors: false\n        onLoaded: { var t = text(); if (t !== view.liveText) { try { view.live = JSON.parse(t); view.liveText = t; } catch (e) { return; } } view.sync(); } }\n    FileView { id: approvalFile; path: view.pcDir + "approval.json"; printErrors: false\n        onLoaded: { var t = text(); if (t === view.approvalText) return; view.approvalText = t\n                    try { view.approval = JSON.parse(t) || ({}); } catch (e) { view.approval = ({}); } } }\n    // One timeline, in order: Claude\'s remarks, what it runs, its approval cards. A card sits\n    // where its tool step is, stays put once answered ("Allowed - running") and turns into\n    // its outcome in place. Kept in a ListModel updated item by item, so nothing redraws\n    // that didn\'t change.\n    property var answered: ({})      // the card you just answered, until its outcome arrives\n    ListModel { id: timelineModel }\n    function stepRow(o) {\n        return { k: String(o.k || ""), t: String(o.t || ""), title: String(o.title || ""), body: String(o.body || ""),\n                 why: String(o.why || ""), decision: String(o.decision || ""), ok: !!o.ok, answered: String(o.answered || "") };\n    }\n    function buildTimeline() {\n        var steps = view.live.steps || [], ap = view.approval || {}, an = view.answered || {};\n        var out = [], apPlaced = false, anPlaced = false;\n        for (var i = 0; i < steps.length; i++) {\n            var st = steps[i];\n            if (st.k === "think") continue;\n            if (st.k === "tool" && ap.id && ap.tuid && st.id === ap.tuid) { out.push(view.stepRow({ k: "ask", title: ap.title, body: ap.body, why: ap.why })); apPlaced = true; continue; }\n            if (st.k === "tool" && an.tuid && st.id === an.tuid) { out.push(view.stepRow({ k: "ask", title: an.title, body: an.body, why: an.why, answered: an.choice })); anPlaced = true; continue; }\n            if (st.k === "card" && an.tuid && st.id === an.tuid) anPlaced = true;\n            out.push(view.stepRow(st));\n        }\n        if (an.choice && !anPlaced) out.push(view.stepRow({ k: "ask", title: an.title, body: an.body, why: an.why, answered: an.choice }));\n        if (ap.id && !apPlaced) out.push(view.stepRow({ k: "ask", title: ap.title, body: ap.body, why: ap.why }));\n        for (var j = 0; j < out.length; j++) {\n            if (j < timelineModel.count) {\n                var cur = timelineModel.get(j);\n                for (var key in out[j]) if (cur[key] !== out[j][key]) timelineModel.setProperty(j, key, out[j][key]);\n            } else timelineModel.append(out[j]);\n        }\n        while (timelineModel.count > out.length) timelineModel.remove(timelineModel.count - 1);\n        // its outcome is in: the answered card has done its job\n        if (an.choice && steps.some(function (x) { return x.k === "card" && x.id === an.tuid; })) view.answered = ({});\n    }\n    onLiveChanged: buildTimeline()\n    onApprovalChanged: buildTimeline()\n    onAnsweredChanged: buildTimeline()\n    Timer { running: true; interval: 1; onTriggered: { liveFile.reload(); approvalFile.reload(); } }   // catch up on open\n    Timer { interval: 350; repeat: true; running: view.busy; triggeredOnStart: true\n        onTriggered: { liveFile.reload(); approvalFile.reload(); } }\n    onBusyChanged: if (!busy) { view.answered = ({}); view.live = ({ busy: false, steps: [] }); view.approval = ({}); view.liveText = ""; view.approvalText = ""; }\n    Process { id: answerProc }\n    function answerApproval(choice) {\n        if (!view.approval || !view.approval.id) return;\n        answerProc.command = ["python3", "-I", Quickshell.env("HOME") + "/.local/lib/panacea-claude/approve-mcp.py",\n                              "--answer", String(view.approval.id), choice];\n        answerProc.running = true;\n        view.answered = { tuid: String(view.approval.tuid || ""), title: view.approval.title, body: view.approval.body,\n                          why: view.approval.why, choice: choice };\n        view.approval = ({});\n    }\n'
LIVE_BLOCK = '                // what Claude is doing right now: one timeline, then the pixel Claude at the bottom\n                Column {\n                    visible: view.busy\n                    width: parent.width; spacing: 10\n                    Repeater {\n                        model: timelineModel\n                        delegate: PanaceaClaudeStep {\n                            required property string k; required property string t; required property string title\n                            required property string body; required property string why; required property string decision\n                            required property bool ok; required property string answered\n                            width: parent.width; sys: view.sys; boxR: view.boxR; rInner: view.rInner\n                            kind: k; text: t; cardTitle: title; cardBody: body; reason: why; outcome: decision; worked: ok; answer: answered\n                            animateIn: true\n                            onChosen: c => view.answerApproval(c)\n                        }\n                    }\n                    Row {\n                        spacing: 10\n                        PanaceaClaudeCritter { px: 2; mood: view.statusMood; anchors.verticalCenter: parent.verticalCenter }\n                        Text { text: ({ thinking: "Thinking", working: "Working", waiting: "Waiting for you" })[view.statusMood]\n                               anchors.verticalCenter: parent.verticalCenter\n                               color: view.sys.colMuted; font { pixelSize: 12; family: view.sys.fontBody } }\n                    }\n                }\n'
MASCOT = '        // the pixel Claude, idle\n        PanaceaClaudeCritter { anchors.horizontalCenter: parent.horizontalCenter; px: 6; mood: "idle" }\n'

# Small QML types used by the patched ChatView, written next to it. (Separate
# files, not inline components: Quickshell 0.3 refused an inline one as a type.)
EXTRA = {
    "PanaceaClaudeStep.qml": 'import QtQuick\n\n// written by chat-patch.py (panacea-claude-bridge)\n// One line of Claude\'s timeline: a remark, a tool it runs, an approval card\n// (then "Allowed - running" once answered), or the outcome of an approved action.\n// Changing kind (ask -> card) happens in place, with the height easing between them.\nItem {\n    id: st\n    property var sys\n    property real boxR: 20\n    property real rInner: 14\n    property string kind: ""          // text | tool | ask | card\n    property string text: ""\n    property string cardTitle: ""\n    property string cardBody: ""\n    property string reason: ""\n    property string outcome: ""       // allow | deny (card)\n    property bool worked: false\n    property string answer: ""        // ask: "" while waiting, then allow | deny\n    property bool animateIn: false\n    signal chosen(string choice)\n\n    readonly property Item shown: kind === "card" ? card : kind === "ask" ? ask : line\n    implicitHeight: shown.height\n    height: implicitHeight\n    clip: true\n    Behavior on height { enabled: st.ready; NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }\n    property bool ready: false\n    opacity: animateIn ? 0 : 1\n    Component.onCompleted: { if (animateIn) opacity = 1; ready = true; }\n    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }\n\n    Text {\n        id: line\n        visible: st.kind === "text" || st.kind === "tool"\n        width: st.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n        maximumLineCount: st.kind === "text" ? 8 : 3; elide: Text.ElideRight\n        text: (st.kind === "tool" ? "›  " : "") + st.text\n        color: st.kind === "text" ? st.sys.colFg : st.sys.colMuted\n        font { pixelSize: st.kind === "text" ? 13 : 12 }\n        lineHeight: 1.15\n    }\n\n    PanaceaClaudeCard {\n        id: card\n        visible: st.kind === "card"\n        width: st.width; sys: st.sys; radius: st.boxR\n        card: ({ title: st.cardTitle, body: st.cardBody, decision: st.outcome, ok: st.worked })\n    }\n\n    Rectangle {\n        id: ask\n        visible: st.kind === "ask"\n        width: st.width; height: Math.max(apCol.implicitHeight, apCritter.height) + 28; radius: st.boxR\n        color: Qt.rgba(1, 1, 1, 0.06)\n        PanaceaClaudeCritter { id: apCritter; x: 14; y: 12; px: 3; mood: st.answer === "" ? "asking" : "working" }\n        Column {\n            id: apCol; x: apCritter.x + apCritter.width + 14; y: 14; width: parent.width - x - 14; spacing: 9\n            Text { width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                   text: "Claude wants to " + st.cardTitle.toLowerCase()\n                   color: st.sys.colFg; font { pixelSize: 13; bold: true; family: st.sys.fontBody } }\n            Text { visible: text.length > 0; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                   text: st.reason; color: st.sys.colMuted; font.pixelSize: 12 }\n            Rectangle {\n                width: parent.width; height: apBody.implicitHeight + 16; radius: st.rInner - 4\n                color: Qt.rgba(0, 0, 0, 0.5)\n                Text { id: apBody; x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WrapAnywhere\n                       textFormat: Text.PlainText; maximumLineCount: 10; elide: Text.ElideRight\n                       text: st.cardBody; color: st.sys.colFg; font { family: st.sys.fontFam; pixelSize: 11 } }\n            }\n            // the buttons, then (same height, so nothing jumps) what you chose\n            Item {\n                width: parent.width; height: 30\n                Row {\n                    anchors.right: parent.right; spacing: 8\n                    opacity: st.answer === "" ? 1 : 0; visible: opacity > 0\n                    Behavior on opacity { NumberAnimation { duration: 160 } }\n                    Repeater {\n                        model: [{ t: "Deny", c: "deny" }, { t: "Allow", c: "allow" }]\n                        delegate: Rectangle {\n                            required property var modelData\n                            width: 86; height: 30; radius: st.rInner\n                            color: modelData.c === "allow" ? (apMa.pressed ? Qt.rgba(1, 1, 1, 0.8) : st.sys.colFg)\n                                   : (apMa.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.08))\n                            Behavior on color { ColorAnimation { duration: 120 } }\n                            Text { anchors.centerIn: parent; text: modelData.t\n                                   color: modelData.c === "allow" ? st.sys.colBg : st.sys.colFg\n                                   font { pixelSize: 12; bold: modelData.c === "allow" } }\n                            MouseArea { id: apMa; anchors.fill: parent; hoverEnabled: true; enabled: st.answer === ""\n                                        cursorShape: Qt.PointingHandCursor; onClicked: st.chosen(modelData.c) }\n                        }\n                    }\n                }\n                Text {\n                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter\n                    opacity: st.answer === "" ? 0 : 1\n                    Behavior on opacity { NumberAnimation { duration: 200 } }\n                    text: st.answer === "allow" ? "Allowed · running" : "Denied"\n                    color: st.sys.colMuted; font { pixelSize: 12; family: st.sys.fontBody }\n                }\n            }\n        }\n    }\n}\n',
    "PanaceaClaudeIcon.qml": 'import QtQuick\nimport QtQuick.Shapes\n\n// written by chat-patch.py (panacea-claude-bridge)\n// Line icons drawn like Panacea\'s own island tab icons (IslandTabIcon.qml):\n// a 20-unit grid, 1.5 strokes, round caps - crisp at any size.\nItem {\n    id: icon\n    property string kind: "attach"     // attach | send | compose\n    property color tint: "white"\n    property real stroke: 1.6\n    implicitWidth: 18; implicitHeight: 18\n    // the path\'s coordinates are scaled, not the item: a scaled Shape blurs its strokes\n    // at fractional display scales, and the stroke width would shrink with it\n    Shape {\n        anchors.fill: parent\n        antialiasing: true\n        preferredRendererType: Shape.CurveRenderer\n        ShapePath {\n            scale: Qt.size(Math.min(icon.width, icon.height) / 20, Math.min(icon.width, icon.height) / 20)\n            fillColor: "transparent"; strokeColor: icon.tint; strokeWidth: icon.stroke\n            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin\n            PathSvg { path: icon.kind === "send" ? "M 10 15.5 L 10 4.5 M 5.5 9 L 10 4.5 L 14.5 9"\n                          : icon.kind === "compose" ? "M 9.5 3.5 L 5.5 3.5 Q 3.5 3.5 3.5 5.5 L 3.5 14.5 Q 3.5 16.5 5.5 16.5 L 14.5 16.5 Q 16.5 16.5 16.5 14.5 L 16.5 10.5 M 14.4 3.4 Q 15.4 2.4 16.4 3.4 L 16.6 3.6 Q 17.6 4.6 16.6 5.6 L 10.6 11.6 L 7.9 12.1 L 8.4 9.4 Z"\n                          : "M 10 4.5 L 10 15.5 M 4.5 10 L 15.5 10" }\n        }\n    }\n}\n',
    "PanaceaClaudeCritter.qml": 'import QtQuick\n\n// written by chat-patch.py (panacea-claude-bridge)\n// The pixel Claude, with a mood for each state of the chat:\n//   idle      empty chat: a slow walk in place, a gentle bob, blinks\n//   thinking  eyes up, "· · ·" lighting up above its head\n//   working   running a tool: quick steps, eyes focused ahead\n//   waiting   a card needs you: it stops and glances toward it\n//   asking    on the card itself: waves one arm, then the other, with a hop\nItem {\n    id: pc\n    property int px: 3\n    property string mood: "idle"\n    property int frame: 0\n    property bool blink: false\n    readonly property color bodyColor: "#d97757"\n    readonly property color eyeColor: "#141414"\n    readonly property color dotColor: Qt.rgba(1, 1, 1, 0.8)\n    readonly property int interval: ({ idle: 320, thinking: 300, working: 150, waiting: 420, asking: 260 })[mood] || 300\n    // 9 rows: 2 above the head (thought dots), 6 of body, 1 of legs\n    readonly property var grid: build(mood, frame, blink)\n    readonly property real hop: mood === "asking" ? (frame % 2 === 0 ? 0 : px)\n                              : mood === "idle" ? (Math.floor(frame / 2) % 2 === 0 ? 0 : px * 0.5)\n                              : 0\n    width: 11 * px; height: 9 * px + px\n\n    onMoodChanged: frame = 0\n\n    function setAt(row, col, ch) { return row.substring(0, col) + ch + row.substring(col + 1); }\n    function build(m, f, b) {\n        var top = ["...........", "..........."];\n        var body = ["..XXXXXXX..", "..XXXXXXX..", "..XXXXXXX..", "XXXXXXXXXXX", "XXXXXXXXXXX", "..XXXXXXX.."];\n        var stand = "..X.X.X.X..", step = ".X.X.X.X...";\n        var legs = stand, er = 2, el = 3, eR = 7;\n        if (m === "idle") {\n            legs = Math.floor(f / 2) % 2 ? step : stand;\n        } else if (m === "thinking") {\n            er = 1;                                            // eyes up\n            if (Math.floor(f / 4) % 2) { el = 4; eR = 8; }     // ...and drifting while it ponders\n            var lit = f % 4;                                   // · · · filling in, then clearing\n            for (var i = 0; i < 3; i++) if (i < lit) top[0] = setAt(top[0], 4 + 2 * i, "D");\n        } else if (m === "working") {\n            legs = f % 2 ? step : stand;\n            el = 4; eR = 8;                                    // focused on the task\n        } else if (m === "waiting") {\n            er = 2; el = 4; eR = 8;                            // a look toward the card\n            top[1] = setAt(top[1], 9, Math.floor(f / 3) % 2 ? "D" : ".");   // a small "!" blink\n            top[0] = setAt(top[0], 9, Math.floor(f / 3) % 2 ? "D" : ".");\n        } else if (m === "asking") {\n            var w = f % 4;\n            if (w === 0) {                                     // left arm up\n                body[1] = setAt(setAt(body[1], 0, "X"), 1, "X"); body[2] = setAt(setAt(body[2], 0, "X"), 1, "X");\n                body[3] = setAt(setAt(body[3], 0, "."), 1, "."); body[4] = setAt(setAt(body[4], 0, "."), 1, ".");\n            } else if (w === 2) {                              // right arm up\n                body[1] = setAt(setAt(body[1], 9, "X"), 10, "X"); body[2] = setAt(setAt(body[2], 9, "X"), 10, "X");\n                body[3] = setAt(setAt(body[3], 9, "."), 10, "."); body[4] = setAt(setAt(body[4], 9, "."), 10, ".");\n            }\n            legs = w % 2 ? step : stand;\n        }\n        if (!b) { body[er] = setAt(setAt(body[er], el, "E"), eR, "E"); }\n        return top.concat(body).concat([legs]);\n    }\n\n    Timer { interval: pc.interval; repeat: true; running: pc.visible; onTriggered: pc.frame = (pc.frame + 1) % 8 }\n    Timer { interval: 3200; repeat: true; running: pc.visible && pc.mood !== "thinking"\n            onTriggered: { pc.blink = true; pcUnblink.restart(); } }\n    Timer { id: pcUnblink; interval: 140; onTriggered: pc.blink = false }\n\n    Grid {\n        columns: 11\n        y: pc.hop\n        Behavior on y { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }\n        Repeater {\n            model: 99\n            Rectangle {\n                required property int index\n                readonly property string ch: pc.grid[Math.floor(index / 11)].charAt(index % 11)\n                width: pc.px; height: pc.px\n                color: ch === "X" ? pc.bodyColor : ch === "E" ? pc.eyeColor : ch === "D" ? pc.dotColor : "transparent"\n            }\n        }\n    }\n}\n',
    "PanaceaClaudeCard.qml": 'import QtQuick\n\n// written by chat-patch.py (panacea-claude-bridge)\n// a finished approval: what ran, and whether it worked\nRectangle {\n    property var sys\n    id: cr\n    property var card: ({})\n    readonly property string outcome: cr.card.decision === "allow" ? (cr.card.ok ? "done" : "failed")\n                                    : cr.card.decision === "deny" ? "denied" : "unanswered"\n    height: crRow.implicitHeight + 18; radius: 11\n    color: Qt.rgba(1, 1, 1, 0.06)\n    Row {\n        id: crRow; x: 12; y: 9; width: parent.width - 24; spacing: 10\n        Rectangle {\n            width: 18; height: 18; radius: 9; anchors.verticalCenter: parent.verticalCenter\n            color: cr.outcome === "done" ? sys.colFg : cr.outcome === "failed" ? sys.colCrit : Qt.rgba(1, 1, 1, 0.1)\n            Text { anchors.centerIn: parent; text: cr.outcome === "done" ? "✓" : cr.outcome === "failed" ? "!" : "×"\n                   color: cr.outcome === "done" ? sys.colBg : cr.outcome === "failed" ? "#ffffff" : sys.colMuted\n                   font { pixelSize: 11; bold: true } }\n        }\n        Column {\n            width: parent.width - 28 - crState.implicitWidth - 10; spacing: 2; anchors.verticalCenter: parent.verticalCenter\n            Text { width: parent.width; elide: Text.ElideRight; text: String(cr.card.title || "")\n                   color: sys.colFg; font { pixelSize: 12; bold: true; family: sys.fontBody } }\n            Text { width: parent.width; elide: Text.ElideRight; maximumLineCount: 1; textFormat: Text.PlainText\n                   visible: text.length > 0; text: String(cr.card.body || "").replace(/\\s*\\n\\s*/g, " ")\n                   color: sys.colMuted; font { family: sys.fontFam; pixelSize: 11 } }\n        }\n        Text { id: crState; anchors.verticalCenter: parent.verticalCenter\n               text: ({ done: "Done", failed: "Failed", denied: "Denied", unanswered: "No answer" })[cr.outcome]\n               color: cr.outcome === "failed" ? sys.colCrit : sys.colMuted; font.pixelSize: 11 }\n    }\n}\n',
}

REPLACEMENTS = [
    ('            id: scroll\n            Layout.fillWidth: true; Layout.fillHeight: true\n', "            id: scroll\n            Layout.fillWidth: true; Layout.fillHeight: true\n            // a slim nub along the island's own edge (3 px in from it), not a chunky bar:\n            // shows while scrolling or hovered, then fades away\n            ScrollBar.vertical: ScrollBar {\n                id: nub\n                parent: scroll\n                x: scroll.width + 15 - width - 3\n                y: scroll.topPadding; height: scroll.availableHeight\n                policy: ScrollBar.AsNeeded\n                width: hovered || pressed ? 6 : 3\n                padding: 0\n                Behavior on width { NumberAnimation { duration: 120 } }\n                background: Item {}\n                contentItem: Rectangle {\n                    implicitWidth: 3; radius: width / 2\n                    color: Qt.rgba(1, 1, 1, nub.pressed ? 0.55 : 0.32)\n                    opacity: nub.active || nub.hovered ? 1 : 0\n                    Behavior on opacity { NumberAnimation { duration: 260 } }\n                }\n            }\n"),
    ('    ColumnLayout {\n        anchors.fill: parent\n        spacing: 10\n', "    ColumnLayout {\n        anchors.fill: parent\n        // the island gives a page 20 px below it but 15 px at the sides; the message\n        // box sits 15 px from the bottom too, so its corners run parallel to the island's\n        anchors.bottomMargin: -8\n        spacing: 10\n"),
    # the message box: concentric corners, no outline, line icons
    ('            radius: height / 2\n            color: Qt.rgba(1, 1, 1, 0.07)\n            border.width: 1\n            border.color: input.activeFocus ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.07)\n', '            // concentric with the island: its corner radius minus the 15 px the content sits inside it.\n            // No outline; focus only lifts the fill a touch.\n            radius: view.boxR\n            color: input.activeFocus ? Qt.rgba(1, 1, 1, 0.075) : Qt.rgba(1, 1, 1, 0.055)\n            Behavior on color { ColorAnimation { duration: 150 } }\n'),
    ('                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 18\n                    color: attachMouse.containsMouse ? Qt.rgba(1,1,1,0.16) : Qt.rgba(1,1,1,0.07)\n                    Glyph { anchors.centerIn: parent; glyph: String.fromCodePoint(0xF03E2); fontFam: view.sys.fontFam; size: 19; color: view.sys.colFg }\n', '                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: view.rInner\n                    color: attachMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"\n                    Behavior on color { ColorAnimation { duration: 150 } }\n                    PanaceaClaudeIcon { anchors.centerIn: parent; width: 18; height: 18; kind: "attach"\n                                        tint: attachMouse.containsMouse ? view.sys.colFg : view.sys.colMuted }\n'),
    ('                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: 18\n                    color: !view.busy && (input.text.trim().length || view.attachments.length) ? view.sys.colFg : Qt.rgba(1,1,1,0.09)\n                    Text { anchors.centerIn: parent; text: "↑"; color: !view.busy && (input.text.trim().length || view.attachments.length) ? view.sys.colBg : view.sys.colMuted; font { pixelSize: 21; bold: true } }\n', '                    readonly property bool ready: !view.busy && (input.text.trim().length || view.attachments.length) > 0\n                    Layout.preferredWidth: 36; Layout.preferredHeight: 36; radius: view.rInner\n                    color: ready ? view.sys.colFg : Qt.rgba(1, 1, 1, 0.06)\n                    Behavior on color { ColorAnimation { duration: 150 } }\n                    PanaceaClaudeIcon { anchors.centerIn: parent; width: 18; height: 18; kind: "send"\n                                        tint: parent.ready ? view.sys.colBg : view.sys.colMuted }\n'),
    # the message box shares the left/right edges of the header, messages and cards
    ('            Layout.leftMargin: 8; Layout.rightMargin: 8\n', '            Layout.leftMargin: -3; Layout.rightMargin: -3   // 12 px from the island, like the bottom\n'),
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
                        // older replies kept only their cards; newer ones keep the whole timeline
                        Repeater { model: msgItem.modelData.timeline || (msgItem.modelData.cards || []).map(function (c) { return Object.assign({ k: "card" }, c); })
                                   delegate: PanaceaClaudeStep { required property var modelData
                                       width: msgItem.width; sys: view.sys; boxR: view.boxR; rInner: view.rInner
                                       kind: String(modelData.k || ""); text: String(modelData.t || ""); cardTitle: String(modelData.title || "")
                                       cardBody: String(modelData.body || ""); outcome: String(modelData.decision || ""); worked: !!modelData.ok } }
                        // yours: a bubble on the right; Claude's: plain text across the width
                        Rectangle {
                            visible: String(msgItem.modelData.content || "").length > 0
                            anchors.right: msgItem.mine ? parent.right : undefined
                            width: msgItem.mine ? message.width + 28 : parent.width
                            height: message.implicitHeight + (msgItem.mine ? 20 : 0)
                            radius: view.boxR
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
