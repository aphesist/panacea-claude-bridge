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
VERSION = "v9"
TAG_PREFIX = "// panacea-local chat patch "
TAG = TAG_PREFIX + VERSION

HEADER = '''        // ''' + TAG + ''': single Claude tab with model pills
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8; Layout.rightMargin: 4
            spacing: 6
            Image {
                source: "file://" + Quickshell.env("HOME") + "/.config/panacea-claude/claude-logo.svg"
                sourceSize: Qt.size(32, 32); Layout.preferredWidth: 16; Layout.preferredHeight: 16
                smooth: true; mipmap: true
            }
            Text { text: "Claude"; color: view.sys.colFg; font { family: view.sys.fontBody; pixelSize: 13; bold: true } }
            Item { Layout.fillWidth: true }
            Repeater {
                model: [{id: "opus", name: "Opus"}, {id: "sonnet", name: "Sonnet"}, {id: "haiku", name: "Haiku"}]
                delegate: Rectangle {
                    id: pill
                    required property var modelData
                    readonly property bool on: (view.sys.cfg.aiModel || "opus") === modelData.id
                    implicitWidth: pillName.implicitWidth + 20; implicitHeight: 26; radius: 13
                    color: on ? Qt.rgba(1, 1, 1, 0.14) : (pillMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.07) : "transparent")
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
            Rectangle {
                implicitWidth: 26; implicitHeight: 26; radius: 13
                color: newMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.1) : "transparent"
                Glyph { anchors.centerIn: parent; glyph: String.fromCodePoint(0xF0415); fontFam: view.sys.fontFam; size: 15; color: view.sys.colMuted }
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

LIVE_PROPS = '    property bool busy: false\n    // live progress + in-chat approval cards, written by bridge.py / approve-mcp.py\n    readonly property string pcDir: Quickshell.env("HOME") + "/.cache/panacea-claude/"\n    readonly property string pcLogo: "file://" + Quickshell.env("HOME") + "/.config/panacea-claude/claude-logo.svg"\n    property var live: ({ busy: false, steps: [] })\n    property var approval: ({})\n    FileView { id: liveFile; path: view.pcDir + "live.json"; printErrors: false\n        onLoaded: { try { view.live = JSON.parse(text()); } catch (e) {} } }\n    FileView { id: approvalFile; path: view.pcDir + "approval.json"; printErrors: false\n        onLoaded: { try { view.approval = JSON.parse(text()) || ({}); } catch (e) { view.approval = ({}); } } }\n    Timer { interval: 350; repeat: true; running: view.busy; triggeredOnStart: true\n        onTriggered: { liveFile.reload(); approvalFile.reload(); } }\n    onBusyChanged: if (!busy) { view.live = ({ busy: false, steps: [] }); view.approval = ({}); }\n    Process { id: answerProc }\n    function answerApproval(choice) {\n        if (!view.approval || !view.approval.id) return;\n        answerProc.command = ["python3", "-I", Quickshell.env("HOME") + "/.local/lib/panacea-claude/approve-mcp.py",\n                              "--answer", String(view.approval.id), choice];\n        answerProc.running = true;\n        view.approval = ({});\n    }\n'
LIVE_BLOCK = '                // what Claude is doing right now, and its approval requests\n                Column {\n                    visible: view.busy\n                    width: parent.width; spacing: 7\n                    Row {\n                        spacing: 8\n                        Image {\n                            source: view.pcLogo; width: 14; height: 14; sourceSize: Qt.size(28, 28); smooth: true\n                            anchors.verticalCenter: parent.verticalCenter\n                            SequentialAnimation on opacity { running: view.busy; loops: Animation.Infinite\n                                NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }\n                                NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine } }\n                            RotationAnimation on rotation { running: view.busy; loops: Animation.Infinite; from: 0; to: 360; duration: 6000 }\n                        }\n                        Text { text: (view.approval && view.approval.id) ? "Waiting for you" : "Working"\n                               color: view.sys.colMuted; font { pixelSize: 12; family: view.sys.fontBody } }\n                    }\n                    Repeater {\n                        model: (view.live.steps || []).slice(-6)\n                        delegate: Text {\n                            required property var modelData\n                            width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                            maximumLineCount: modelData.k === "text" ? 4 : 3; elide: Text.ElideRight\n                            leftPadding: modelData.k === "text" ? 0 : 22\n                            text: (modelData.k === "tool" ? "›  " : "") + modelData.t\n                            color: modelData.k === "text" ? view.sys.colFg : view.sys.colMuted\n                            opacity: modelData.k === "think" ? 0.75 : 1\n                            font { pixelSize: 12; italic: modelData.k === "think" }\n                        }\n                    }\n                    Rectangle {\n                        visible: !!(view.approval && view.approval.id)\n                        width: parent.width; height: apCol.implicitHeight + 26; radius: 14\n                        color: Qt.rgba(1, 1, 1, 0.06); border.color: "#d97757"; border.width: 1\n                        Column {\n                            id: apCol; x: 13; y: 13; width: parent.width - 26; spacing: 9\n                            Text { width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                                   text: "Claude wants to " + String((view.approval && view.approval.title) || "").toLowerCase()\n                                   color: view.sys.colFg; font { pixelSize: 13; bold: true; family: view.sys.fontBody } }\n                            Text { visible: text.length > 0; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText\n                                   text: String((view.approval && view.approval.why) || "")\n                                   color: view.sys.colMuted; font.pixelSize: 12 }\n                            Rectangle {\n                                width: parent.width; height: apBody.implicitHeight + 16; radius: 8\n                                color: Qt.rgba(0, 0, 0, 0.55); border.color: view.sys.colLine; border.width: 1\n                                Text { id: apBody; x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WrapAnywhere\n                                       textFormat: Text.PlainText; maximumLineCount: 10; elide: Text.ElideRight\n                                       text: String((view.approval && view.approval.body) || "")\n                                       color: view.sys.colFg; font { family: view.sys.fontFam; pixelSize: 11 } }\n                            }\n                            Row {\n                                anchors.right: parent.right; spacing: 8\n                                Repeater {\n                                    model: [{ t: "Deny", c: "deny" }, { t: "Allow", c: "allow" }]\n                                    delegate: Rectangle {\n                                        required property var modelData\n                                        width: 86; height: 30; radius: 15\n                                        color: modelData.c === "allow" ? view.sys.colFg\n                                               : (apMa.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.08))\n                                        Text { anchors.centerIn: parent; text: modelData.t\n                                               color: modelData.c === "allow" ? view.sys.colBg : view.sys.colFg\n                                               font { pixelSize: 12; bold: modelData.c === "allow" } }\n                                        MouseArea { id: apMa; anchors.fill: parent; hoverEnabled: true\n                                                    cursorShape: Qt.PointingHandCursor; onClicked: view.answerApproval(modelData.c) }\n                                    }\n                                }\n                            }\n                        }\n                    }\n                }\n'
MASCOT = '        // a little orange pixel Claude, walking in place\n        Item {\n            id: critter\n            anchors.horizontalCenter: parent.horizontalCenter\n            readonly property int px: 6\n            readonly property var body: ["..XXXXXXX..", "..XXXXXXX..", "..XEXXXEX..", "XXXXXXXXXXX",\n                                         "XXXXXXXXXXX", "..XXXXXXX.."]\n            readonly property var legs: [["..X.X.X.X.."], [".X.X.X.X..."]]\n            property int frame: 0\n            property bool blink: false\n            readonly property var rows: body.concat(legs[frame])\n            width: 11 * px; height: rows.length * px + 8\n            Timer { interval: 300; repeat: true; running: critter.visible; onTriggered: critter.frame = 1 - critter.frame }\n            Timer { interval: 3400; repeat: true; running: critter.visible\n                    onTriggered: { critter.blink = true; unblink.restart(); } }\n            Timer { id: unblink; interval: 160; onTriggered: critter.blink = false }\n            Item {\n                id: sprite; width: parent.width; height: critter.rows.length * critter.px\n                SequentialAnimation on y { running: critter.visible; loops: Animation.Infinite\n                    NumberAnimation { from: 4; to: 0; duration: 300; easing.type: Easing.OutQuad }\n                    NumberAnimation { from: 0; to: 4; duration: 300; easing.type: Easing.InQuad } }\n                Repeater {\n                    model: critter.rows.length * 11\n                    delegate: Rectangle {\n                        required property int index\n                        readonly property string ch: critter.rows[Math.floor(index / 11)].charAt(index % 11)\n                        x: (index % 11) * critter.px; y: Math.floor(index / 11) * critter.px\n                        width: critter.px; height: critter.px\n                        visible: ch !== "."\n                        color: ch === "E" && !critter.blink ? "#141414" : "#d97757"\n                    }\n                }\n            }\n        }\n'

REPLACEMENTS = [
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
