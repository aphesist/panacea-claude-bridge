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
VERSION = "v1"
TAG_PREFIX = "// panacea-local chat patch "
TAG = TAG_PREFIX + VERSION

HEADER = '''        // ''' + TAG + ''': single Claude tab with model pills
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8; Layout.rightMargin: 4
            spacing: 6
            Text { text: "✦"; color: view.sys.colFg; font.pixelSize: 16 }
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

REPLACEMENTS = [
    # always the API chat, never the web tabs
    ("    property string service: sys.islandChatService\n",
     "    property string service: \"chat\"   " + TAG + "\n"
     "    Component.onCompleted: sys.islandChatService = \"chat\"\n"),
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
    tmp = p + ".patch-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def main() -> int:
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
