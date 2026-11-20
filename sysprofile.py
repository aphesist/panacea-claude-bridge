#!/usr/bin/env python3
"""The machine profile the island's Claude gets with every message.

Collects live facts about this computer (hardware, OS, desktop, services,
GPU, disks, network) and adds your own notes from
~/.config/panacea-claude/notes.md (house rules, where things live, what to
be careful with). bridge.py appends the result to its system prompt on every
run, new chat or not, so Claude always starts out knowing the machine.

    sysprofile.py            print the profile
    sysprofile.py --write    write ~/.cache/panacea-claude/system-profile.md

bridge.py rebuilds it at startup, every few hours, and after package changes.
Nothing secret is collected: no keys, tokens, serial numbers or IP addresses.
"""
import os, pathlib, platform, pwd, re, shutil, subprocess, sys, time

HOME = pathlib.Path.home()
OUT = HOME / ".cache/panacea-claude/system-profile.md"
NOTES = HOME / ".config/panacea-claude/notes.md"


def sh(*cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def read(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return ""


def os_release():
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)', read("/etc/os-release"), re.M)
    return m.group(1) if m else platform.system()


def cpu():
    m = re.search(r"^model name\s*:\s*(.+)$", read("/proc/cpuinfo"), re.M)
    return f"{m.group(1) if m else platform.processor()}, {os.cpu_count()} threads"


def memory():
    m = re.search(r"^MemTotal:\s+(\d+)", read("/proc/meminfo"), re.M)
    return f"{round(int(m.group(1)) / 1048576)} GiB" if m else "?"


def gpus():
    lines = [l.split(": ", 1)[1] for l in sh("lspci").splitlines()
             if re.search(r"VGA|3D controller|Display controller", l) and ": " in l]
    nv = read("/sys/module/nvidia/version").strip()   # not nvidia-smi: it wakes a sleeping dGPU
    if nv:
        lines.append(f"NVIDIA driver: {nv}")
    return lines


def displays():
    out = []
    for block in sh("hyprctl", "monitors").split("\n\n"):
        name = re.search(r"^Monitor (\S+)", block, re.M)
        mode = re.search(r"^\s+(\d+x\d+@[\d.]+)", block, re.M)
        scale = re.search(r"scale: ([\d.]+)", block)
        if name and mode:
            out.append(f"{name.group(1)} {mode.group(1)} scale {scale.group(1) if scale else '1'}")
    return out


def disks():
    out = []
    for l in sh("lsblk", "-dno", "NAME,SIZE,MODEL").splitlines():
        if not l.startswith(("loop", "zram")):
            out.append(" ".join(l.split()))
    root = sh("df", "-h", "--output=fstype,size,used,avail", "/").splitlines()[1:]
    if root:
        f = root[0].split()
        out.append(f"/ is {f[0]}, {f[1]} ({f[2]} used, {f[3]} free)")
    return out


def services(user):
    args = ["systemctl"] + (["--user"] if user else []) + \
           ["list-units", "--type=service", "--state=running", "--no-legend", "--plain"]
    names = [l.split()[0].removesuffix(".service") for l in sh(*args).splitlines() if l.strip()]
    boring = re.compile(r"^(dbus|systemd-|user@|getty|dconf|gvfs|at-spi|xdg-|pipewire|wireplumber|"
                        r"polkit|rtkit|udisks|accounts|gnome-keyring|kmod|modprobe|ldconfig)")
    return [n for n in names if not boring.match(n) and "@" not in n]


def battery():
    for b in sorted(pathlib.Path("/sys/class/power_supply").glob("BAT*")):
        full = read(b / "energy_full") or read(b / "charge_full")
        design = read(b / "energy_full_design") or read(b / "charge_full_design")
        cap = read(b / "capacity")
        health = f", health {round(100 * int(full) / int(design))}%" if full and design else ""
        return f"{cap}% now{health}, {read(b / 'status').lower()}"
    return ""


def versions():
    v = []
    hypr = sh("hyprctl", "version")
    m = re.search(r"Hyprland ([\d.]+)", hypr)
    if m:
        v.append(f"Hyprland {m.group(1)} (Lua config)")
    for name, cmd in (("Quickshell", ["qs", "--version"]), ("Claude Code", ["claude", "--version"])):
        m = re.search(r"\d+\.\d+[\w.-]*", sh(*cmd))
        if m:
            v.append(f"{name} {m.group(0)}")
    panacea = read(HOME / ".config/panacea/VERSION") or read(HOME / ".config/panacea/version")
    if panacea:
        v.append(f"Panacea {panacea}")
    return v


def packages():
    n = len(sh("pacman", "-Qq").splitlines())
    aur = len(sh("pacman", "-Qmq").splitlines())
    helper = next((h for h in ("yay", "paru") if shutil.which(h)), None)
    return f"{n} packages ({aur} from the AUR{', helper: ' + helper if helper else ''})"


def build():
    dmi = lambda f: read(f"/sys/class/dmi/id/{f}")
    p = ["# This computer (live profile, refreshed automatically)", ""]
    def section(title, items):
        items = [i for i in items if i]
        if items:
            p.append(f"{title}:")
            p.extend(f"- {i}" for i in items)
            p.append("")
    section("Hardware", [
        f"{dmi('sys_vendor')} {dmi('product_name')} (BIOS {dmi('bios_version')})".strip(),
        f"CPU: {cpu()}", f"RAM: {memory()}",
        *[f"GPU: {g}" for g in gpus()],
        *[f"Display: {d}" for d in displays()],
        *[f"Disk: {d}" for d in disks()],
        f"Battery: {battery()}" if battery() else "",
    ])
    section("System", [
        f"{os_release()}, kernel {platform.release()}", packages(), *versions(),
        f"Login shell: {os.path.basename(pwd.getpwuid(os.getuid()).pw_shell)}",
        f"Boot: {read('/proc/cmdline').split(' root=')[0]} ..." if read("/proc/cmdline") else "",
    ])
    section("Running system services", [", ".join(services(False))])
    section("Running user services", [", ".join(services(True))])
    notes = read(NOTES)
    if notes:
        p += ["# Notes from the owner (follow these)", "", notes, ""]
    p.append(f"(profile built {time.strftime('%Y-%m-%d %H:%M')})")
    return "\n".join(p)


if __name__ == "__main__":
    text = build()
    if "--write" in sys.argv:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(text + "\n")
        os.replace(tmp, OUT)
    else:
        print(text)
