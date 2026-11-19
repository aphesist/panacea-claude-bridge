import QtQuick

// written by chat-patch.py (panacea-claude-bridge)
// The pixel Claude, with a mood for each state of the chat:
//   idle      empty chat: a slow walk in place, a gentle bob, blinks
//   thinking  eyes up, "· · ·" lighting up above its head
//   working   running a tool: quick steps, eyes focused ahead
//   waiting   a card needs you: it stops and glances toward it
//   asking    on the card itself: waves one arm, then the other, with a hop
Item {
    id: pc
    property int px: 3
    property string mood: "idle"
    property int frame: 0
    property bool blink: false
    readonly property color bodyColor: "#d97757"
    readonly property color eyeColor: "#141414"
    readonly property color dotColor: Qt.rgba(1, 1, 1, 0.8)
    readonly property int interval: ({ idle: 320, thinking: 300, working: 150, waiting: 420, asking: 260 })[mood] || 300
    // 9 rows: 2 above the head (thought dots), 6 of body, 1 of legs
    readonly property var grid: build(mood, frame, blink)
    readonly property real hop: mood === "asking" ? (frame % 2 === 0 ? 0 : px)
                              : mood === "idle" ? (Math.floor(frame / 2) % 2 === 0 ? 0 : px * 0.5)
                              : 0
    width: 11 * px; height: 9 * px + px

    onMoodChanged: frame = 0

    function setAt(row, col, ch) { return row.substring(0, col) + ch + row.substring(col + 1); }
    function build(m, f, b) {
        var top = ["...........", "..........."];
        var body = ["..XXXXXXX..", "..XXXXXXX..", "..XXXXXXX..", "XXXXXXXXXXX", "XXXXXXXXXXX", "..XXXXXXX.."];
        var stand = "..X.X.X.X..", step = ".X.X.X.X...";
        var legs = stand, er = 2, el = 3, eR = 7;
        if (m === "idle") {
            legs = Math.floor(f / 2) % 2 ? step : stand;
        } else if (m === "thinking") {
            er = 1;                                            // eyes up
            if (Math.floor(f / 4) % 2) { el = 4; eR = 8; }     // ...and drifting while it ponders
            var lit = f % 4;                                   // · · · filling in, then clearing
            for (var i = 0; i < 3; i++) if (i < lit) top[0] = setAt(top[0], 4 + 2 * i, "D");
        } else if (m === "working") {
            legs = f % 2 ? step : stand;
            el = 4; eR = 8;                                    // focused on the task
        } else if (m === "waiting") {
            er = 2; el = 4; eR = 8;                            // a look toward the card
            top[1] = setAt(top[1], 9, Math.floor(f / 3) % 2 ? "D" : ".");   // a small "!" blink
            top[0] = setAt(top[0], 9, Math.floor(f / 3) % 2 ? "D" : ".");
        } else if (m === "asking") {
            var w = f % 4;
            if (w === 0) {                                     // left arm up
                body[1] = setAt(setAt(body[1], 0, "X"), 1, "X"); body[2] = setAt(setAt(body[2], 0, "X"), 1, "X");
                body[3] = setAt(setAt(body[3], 0, "."), 1, "."); body[4] = setAt(setAt(body[4], 0, "."), 1, ".");
            } else if (w === 2) {                              // right arm up
                body[1] = setAt(setAt(body[1], 9, "X"), 10, "X"); body[2] = setAt(setAt(body[2], 9, "X"), 10, "X");
                body[3] = setAt(setAt(body[3], 9, "."), 10, "."); body[4] = setAt(setAt(body[4], 9, "."), 10, ".");
            }
            legs = w % 2 ? step : stand;
        }
        if (!b) { body[er] = setAt(setAt(body[er], el, "E"), eR, "E"); }
        return top.concat(body).concat([legs]);
    }

    Timer { interval: pc.interval; repeat: true; running: pc.visible; onTriggered: pc.frame = (pc.frame + 1) % 8 }
    Timer { interval: 3200; repeat: true; running: pc.visible && pc.mood !== "thinking"
            onTriggered: { pc.blink = true; pcUnblink.restart(); } }
    Timer { id: pcUnblink; interval: 140; onTriggered: pc.blink = false }

    Grid {
        columns: 11
        y: pc.hop
        Behavior on y { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }
        Repeater {
            model: 99
            Rectangle {
                required property int index
                readonly property string ch: pc.grid[Math.floor(index / 11)].charAt(index % 11)
                width: pc.px; height: pc.px
                color: ch === "X" ? pc.bodyColor : ch === "E" ? pc.eyeColor : ch === "D" ? pc.dotColor : "transparent"
            }
        }
    }
}
