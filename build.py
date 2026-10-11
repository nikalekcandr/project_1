#!/usr/bin/env python3
"""
Сборка «Генштаба» в настоящую программу: своя иконка со звездой, без консоли и без значка Python.

  python build.py                 собрать, установить, создать ярлыки и автозапуск, открыть
  python build.py --no-install    только собрать (результат в build/dist)
  python build.py --no-autostart  установить без запуска при входе в систему
  python build.py --uninstall     удалить программу, ярлыки и автозапуск (данные в ~/.genshtab остаются)

Куда ставится:
  Windows  %LOCALAPPDATA%\\Programs\\Genshtab\\Genshtab.exe, ярлык «Генштаб» на рабочем столе и в «Пуске»
  macOS    ~/Applications/Генштаб.app
  Linux    ~/.local/share/genshtab-app и пункт «Генштаб» в меню приложений

Старый Темп при установке закрывается и убирается: программа, ярлыки, автозапуск и страж. Его данные
(~/.tempo) остаются на месте, а Генштаб при первом запуске копирует их к себе (~/.genshtab).

Нужен Python 3.9+ с tkinter. Интернет нужен один раз — скачать PyInstaller (и pystray для трея). Если Темп
уже собирался на этом компьютере, его окружение для сборки подхватится, и интернет не нужен совсем.
"""

import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "genshtab.py"
BUILD = HERE / "build"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
NAME = "Genshtab"
TITLE = "Генштаб"
LEGACY_NAME = "Tempo"
LEGACY_TITLE = "Темп"


def fail(msg):
    say("\nНе получилось: " + msg)
    sys.exit(1)


def load_tempo():
    spec = importlib.util.spec_from_file_location("genshtab_src", SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_python():
    if sys.version_info < (3, 9):
        fail(f"нужен Python 3.9 или новее, а запущен {sys.version.split()[0]}.")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        hint = ("Переустанови Python с python.org и оставь галочку «tcl/tk and IDLE»." if IS_WIN else
                "Поставь Python с python.org: в нём tkinter уже есть." if IS_MAC else
                "Поставь пакет python3-tk.")
        fail("в этом Python нет tkinter. " + hint)
    if not SRC.exists():
        fail(f"рядом с build.py нет genshtab.py ({SRC}).")


# ─────────────── окружение для сборки ───────────────
#
# Раньше окружение создавалось внутри папки с архивом, молча и заново для каждой версии.
# На Windows это могло «висеть» без единой строки на экране. Теперь:
#   1. сначала ищется готовое окружение, где PyInstaller уже стоит (общее или от прошлых версий);
#   2. общее окружение живёт в одном месте и переживает обновления;
#   3. всё, что может идти долго, идёт отдельным процессом с живым выводом и отметками времени;
#   4. если окружение не создаётся, пакеты ставятся в сам Python (pip --user).

NEEDED = ["pyinstaller"] + ([] if IS_MAC else ["pystray", "pillow"])
MODULES = ["PyInstaller", "tkinter"] + ([] if IS_MAC else ["pystray", "PIL"])
# Только проверка, что модули на месте: импорт pystray на Linux без экрана падает сам по себе.
IMPORTS = ("import importlib.util as u, sys; "
           f"sys.exit(0 if all(u.find_spec(m) for m in {MODULES!r}) else 1)")
LOG = BUILD / "build.log"


def shared_env(name=NAME):
    if IS_WIN:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / name
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support" / name
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / name.lower()
    return base / "build-env"


def env_python(env):
    return Path(env) / ("Scripts/python.exe" if IS_WIN else "bin/python")


def log(msg):
    try:
        BUILD.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def say(msg=""):
    try:
        print(msg, flush=True)
    except (UnicodeEncodeError, OSError):
        try:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
        except OSError:
            pass
    if msg:
        log(msg)


def run(args, title, timeout=900, quiet_ok=False):
    """Запускает процесс, показывает его вывод и каждые 15 секунд тишины пишет, что работа идёт.
    Возвращает (код, хвост вывода). Код None — вышло время."""
    import queue
    import threading
    log("$ " + " ".join(str(a) for a in args))
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    flags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW: дочерний процесс не открывает своё окно
    try:
        p = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=flags, cwd=str(BUILD))
    except OSError as e:
        log(f"не запустилось: {e}")
        return 1, str(e)
    q = queue.Queue()

    def pump():
        for raw in iter(p.stdout.readline, b""):
            q.put(raw.decode("utf-8", "replace").rstrip())
        q.put(None)

    threading.Thread(target=pump, daemon=True).start()
    started = last = time.time()
    tail = []
    done = False
    while not done:
        try:
            line = q.get(timeout=1)
        except queue.Empty:
            line = ""
        if line is None:
            done = True
        elif line:
            tail = (tail + [line])[-30:]
            log(line)
            if not quiet_ok:
                say("   " + line[:160])
            last = time.time()
        now = time.time()
        if now - last >= 15:
            say(f"   …{title}: идёт {int(now - started)} с")
            last = now
        if now - started > timeout:
            p.kill()
            log("время вышло")
            return None, "\n".join(tail)
    p.wait()
    log(f"код {p.returncode}")
    return p.returncode, "\n".join(tail)


def works(py):
    """В этом Python уже есть всё для сборки?"""
    py = Path(py)
    if not py.exists():
        return False
    code, _ = run([py, "-c", IMPORTS], "проверка", timeout=120, quiet_ok=True)
    return code == 0


def candidates():
    """Готовые окружения: общее, от Темпа, своё и от прошлых версий в соседних папках."""
    seen, out = set(), []

    def add(env):
        py = env_python(env)
        key = str(py).lower()
        if key not in seen and py.exists():
            seen.add(key)
            out.append(py)

    add(shared_env())
    add(shared_env(LEGACY_NAME))  # окружение, в котором собирался Темп: PyInstaller там уже стоит
    add(BUILD / "venv")
    for root in {HERE.parent, HERE.parent.parent}:
        try:
            for pattern in ("*/build/venv", "*/*/build/venv"):
                for env in sorted(root.glob(pattern), key=lambda p: -p.stat().st_mtime)[:12]:
                    add(env)
        except OSError:
            pass
    return out


def make_env(env):
    py = env_python(env)
    if py.exists() and run([py, "-m", "pip", "--version"], "проверка pip", timeout=120, quiet_ok=True)[0] == 0:
        return py
    say("Создаю окружение для сборки (один раз на все версии)…")
    say(f"   {env}")
    shutil.rmtree(env, ignore_errors=True)
    env.parent.mkdir(parents=True, exist_ok=True)
    # Сначала без pip: это секунды. pip отдельным шагом, чтобы было видно, что происходит.
    code, tail = run([sys.executable, "-m", "venv", "--without-pip", env], "окружение", timeout=300)
    if code != 0 or not py.exists():
        say("   Окружение не создалось." + (" Вышло время." if code is None else ""))
        return None
    say("Ставлю pip в окружение…")
    code, tail = run([py, "-m", "ensurepip", "--upgrade", "--default-pip"], "pip", timeout=600)
    if code != 0:
        say("   pip не встал." + (" Вышло время." if code is None else ""))
        return None
    return py


def pip_install(py, user=False):
    say("Ставлю " + ", ".join(NEEDED) + " (один раз, дальше из кэша)…")
    args = [py, "-m", "pip", "install", "--timeout", "30", "--retries", "3", "--progress-bar", "off"]
    if user:
        args.append("--user")
    code, tail = run(args + NEEDED, "установка пакетов", timeout=1200)
    return code == 0 and works(py)


def build_python():
    """Python, в котором есть PyInstaller. Ищет готовое, иначе ставит, иначе объясняет, что делать."""
    say("Ищу готовое окружение для сборки…")
    for py in candidates():
        if works(py):
            say(f"   Есть: {py.parent.parent}")
            return py
    if works(sys.executable):
        say("   Всё нужное уже стоит в самом Python.")
        return Path(sys.executable)
    env = shared_env()
    py = make_env(env)
    if py and pip_install(py):
        return py
    say("\nОтдельное окружение не получилось. Ставлю пакеты прямо в Python (pip --user)…")
    if pip_install(Path(sys.executable), user=True):
        return Path(sys.executable)
    fail("не удалось поставить PyInstaller.\n"
         "Проверь интернет и запусти сборку ещё раз — всё, что уже скачано, не пропадёт.\n"
         f"Подробности в {LOG} — пришли этот файл, если не выйдет снова.\n"
         "А пока Генштаб можно запустить без сборки: «Запустить без сборки (Windows).bat».")


def disable_quick_edit():
    """В консоли Windows клик мышью по окну ставит программу на паузу («Выделить» в заголовке),
    и сборка выглядит зависшей. Выключаем это для окна сборки."""
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


def write_icons(tempo):
    BUILD.mkdir(parents=True, exist_ok=True)
    png = BUILD / "genshtab.png"
    png.write_bytes(tempo.png_bytes(256))
    if IS_WIN:
        ico = BUILD / "genshtab.ico"
        ico.write_bytes(tempo.ico_bytes())
        return ico
    if IS_MAC:
        icns = BUILD / "genshtab.icns"
        if icns.exists():
            icns.unlink()
        if tempo.Integration()._mac_icns(icns):
            return icns
        return None
    return png


def write_version_file(version):
    parts = [int(x) for x in (version.split(".") + ["0", "0", "0"])[:4] if x.isdigit()] + [0, 0, 0, 0]
    a, b, c, d = parts[:4]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, {d}), prodvers=({a}, {b}, {c}, {d}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('FileDescription', '{TITLE}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('OriginalFilename', '{NAME}.exe'),
      StringStruct('ProductName', '{TITLE}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])
  ]
)
"""
    path = BUILD / "version.txt"
    path.write_text(text, encoding="utf-8")
    return path


def run_pyinstaller(py, icon, version):
    dist, work = BUILD / "dist", BUILD / "work"
    shutil.rmtree(dist, ignore_errors=True)
    args = [str(py), "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
            "--name", NAME, "--distpath", str(dist), "--workpath", str(work), "--specpath", str(BUILD),
            "--log-level", "WARN"]
    if icon:
        args += ["--icon", str(icon)]
    if IS_WIN:
        args += ["--version-file", str(write_version_file(version)), "--hidden-import", "pystray._win32"]
    elif IS_MAC:
        args += ["--osx-bundle-identifier", "local.genshtab.app"]
    else:
        args += ["--hidden-import", "pystray._xorg"]
    args.append(str(SRC))
    say("Собираю программу (минуту-две, антивирус может замедлить)…")
    code, tail = run(args, "сборка", timeout=1800)
    if code != 0:
        fail("PyInstaller завершился с ошибкой" + (" (вышло время)" if code is None else "") +
             f", текст выше. Полный журнал: {LOG}")
    if IS_MAC:
        app = dist / f"{NAME}.app"
        info_path = app / "Contents" / "Info.plist"
        with open(info_path, "rb") as f:
            info = plistlib.load(f)
        info.update({"CFBundleName": TITLE, "CFBundleDisplayName": TITLE, "CFBundleShortVersionString": version,
                     "CFBundleVersion": version, "NSHighResolutionCapable": True,
                     "LSApplicationCategoryType": "public.app-category.productivity"})
        with open(info_path, "wb") as f:
            plistlib.dump(info, f)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], capture_output=True)
        return app
    return dist / NAME


def stop_running(tempo):
    try:
        if tempo.SingleInstance().ping("quit"):
            say("Закрываю запущенный Генштаб, чтобы обновить (данные сохраняются)…")
            for _ in range(20):
                time.sleep(0.5)
                if not tempo.SingleInstance().ping("ping"):
                    break
            time.sleep(1)
    except Exception:
        pass
    try:
        if tempo.stop_legacy():
            say("Закрыл старый Темп: его данные Генштаб заберёт сам при первом запуске.")
    except Exception:
        pass
    if IS_WIN:
        subprocess.run(["taskkill", "/IM", f"{LEGACY_NAME}.exe", "/F"], capture_output=True)


def remove_legacy(tempo):
    """Убирает установленный Темп: программу, ярлыки, автозапуск и стража. Данные ~/.tempo не трогаются."""
    removed = []
    try:
        removed += tempo.cleanup_legacy()
    except Exception as e:
        log(f"уборка Темпа: {e}")
    if IS_WIN:
        old = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / LEGACY_NAME
    elif IS_MAC:
        old = Path.home() / "Applications" / f"{LEGACY_TITLE}.app"
    else:
        old = Path.home() / ".local" / "share" / "tempo-app"
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
        if not old.exists():
            removed.append(str(old))
    for p in removed:
        say(f"Убрано от Темпа: {p}")
    return removed


def free_target(target):
    """Старую версию отодвигаем в сторону, а удаляем только после того, как новая встала.
    Возвращает путь к старой версии (или None)."""
    for stale in target.parent.glob(target.name + ".old-*"):
        shutil.rmtree(stale, ignore_errors=True)
    if not target.exists():
        return None
    old = target.with_name(f"{target.name}.old-{int(time.time())}")
    for attempt in range(3):
        try:
            os.replace(target, old)
            return old
        except OSError:
            if attempt == 0 and IS_WIN:
                say("Генштаб ещё открыт — закрываю принудительно…")
                subprocess.run(["taskkill", "/IM", f"{NAME}.exe", "/F"], capture_output=True)
            time.sleep(2)
    fail(f"не удалось заменить {target}. Закрой Генштаб (значок в трее → Выход) и запусти сборку снова.")


def install(tempo, built, autostart):
    integ = tempo.Integration()
    if IS_WIN:
        target = Path(os.environ["LOCALAPPDATA"]) / "Programs" / NAME
        exe = target / f"{NAME}.exe"
    elif IS_MAC:
        target = Path.home() / "Applications" / f"{TITLE}.app"
        exe = target / "Contents" / "MacOS" / NAME
    else:
        target = Path.home() / ".local" / "share" / "genshtab-app"
        exe = target / NAME
    old = free_target(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(built, target, symlinks=True)
    except OSError as e:
        shutil.rmtree(target, ignore_errors=True)
        if old is not None:
            os.replace(old, target)
            fail(f"не удалось скопировать новую версию ({e}). Старая версия осталась на месте.")
        fail(f"не удалось скопировать программу ({e}).")
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)
    say(f"Установлено: {target}")

    made = []
    cmd = [str(exe)]
    if IS_WIN:
        script = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {\n"
            "  if (-not $dir) { continue }\n"
            f"  $path = Join-Path $dir {tempo.ps_str(TITLE + '.lnk')}\n"
            "  $s = $ws.CreateShortcut($path)\n"
            f"  $s.TargetPath = {tempo.ps_str(exe)}\n"
            "  $s.Arguments = ''\n"
            f"  $s.WorkingDirectory = {tempo.ps_str(target)}\n"
            f"  $s.IconLocation = {tempo.ps_str(str(exe) + ',0')}\n"
            f"  $s.Description = {tempo.ps_str('Генштаб: приказ на день, штурмы, сводки и разведка')}\n"
            "  $s.Save()\n"
            "  Write-Output $path\n"
            "}\n")
        code, out, err = tempo.run_powershell(script)
        if code == 0:
            made = [line.strip() for line in out.splitlines() if line.strip()]
        else:
            say("Ярлыки создать не удалось: " + err.strip())
        if autostart:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, integ.RUN_KEY) as k:
                winreg.SetValueEx(k, integ.RUN_VALUE, 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(cmd + ["--minimized"]))
    elif IS_MAC:
        made = [str(target)]
        if autostart:
            agent = integ._mac_agent()
            agent.parent.mkdir(parents=True, exist_ok=True)
            with open(agent, "wb") as f:
                plistlib.dump({"Label": tempo.BUNDLE_ID, "RunAtLoad": True,
                               "ProgramArguments": ["/usr/bin/open", "-a", str(target), "--args", "--minimized"]}, f)
    else:
        shutil.copy2(BUILD / "genshtab.png", target / "genshtab.png")
        entry = ("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Генштаб\n"
                 "Comment=Генштаб: приказ на день, штурмы, сводки и разведка\n"
                 f"Exec={exe}\nIcon={target / 'genshtab.png'}\nTerminal=false\nCategories=Office;Utility;\n"
                 "StartupWMClass=Genshtab\n")
        menu = Path.home() / ".local" / "share" / "applications" / "genshtab.desktop"
        menu.parent.mkdir(parents=True, exist_ok=True)
        menu.write_text(entry, encoding="utf-8")
        made.append(str(menu))
        if autostart:
            auto = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "genshtab.desktop"
            auto.parent.mkdir(parents=True, exist_ok=True)
            auto.write_text(entry.replace(f"Exec={exe}", f"Exec={exe} --minimized"), encoding="utf-8")
    for path in made:
        say(f"Ярлык: {path}")
    if autostart:
        say("Автозапуск включён: при входе в систему Генштаб стартует свёрнутым в трей "
            "(выключается в настройках программы).")
    return exe, target


def uninstall(tempo):
    stop_running(tempo)
    integ = tempo.Integration()
    removed = []
    try:
        integ.set_autostart(False)
    except Exception:
        pass
    if hasattr(tempo, "guard_set"):
        try:
            if tempo.guard_set(False)[0] and IS_WIN:
                removed.append(f"задача Планировщика «{tempo.GUARD_TASK}»")
        except Exception:
            pass
    if IS_WIN:
        target = Path(os.environ["LOCALAPPDATA"]) / "Programs" / NAME
        code, out, _err = tempo.run_powershell(
            "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {\n"
            f"  $p = Join-Path $dir {tempo.ps_str(TITLE + '.lnk')}\n"
            "  if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force; Write-Output $p }\n}")
        removed += [line.strip() for line in out.splitlines() if line.strip()]
    elif IS_MAC:
        target = Path.home() / "Applications" / f"{TITLE}.app"
    else:
        target = Path.home() / ".local" / "share" / "genshtab-app"
        for p in (Path.home() / ".local" / "share" / "applications" / "genshtab.desktop",):
            if p.exists():
                p.unlink()
                removed.append(str(p))
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        removed.append(str(target))
    for p in removed:
        say(f"Удалено: {p}")
    say(f"Данные остались в {tempo.DATA_DIR}.")


def main(argv):
    disable_quick_edit()
    try:
        BUILD.mkdir(parents=True, exist_ok=True)
        LOG.write_text("", encoding="utf-8")
    except OSError:
        pass
    say(f"{TITLE}: сборка программы")
    say(f"Python {sys.version.split()[0]}: {sys.executable}\n")
    check_python()
    tempo = load_tempo()
    say(f"Версия {tempo.VERSION}")
    if "--uninstall" in argv:
        uninstall(tempo)
        return 0
    py = build_python()
    icon = write_icons(tempo)
    built = run_pyinstaller(py, icon, tempo.VERSION)
    say(f"Собрано: {built}")
    if "--no-install" in argv:
        return 0
    stop_running(tempo)
    exe, target = install(tempo, built, autostart="--no-autostart" not in argv)
    remove_legacy(tempo)
    if "--no-launch" not in argv:
        if IS_MAC:
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen([str(exe)], cwd=str(exe.parent),
                             creationflags=0x00000008 if IS_WIN else 0,  # DETACHED_PROCESS
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say("\nГотово. Генштаб — обычная программа: открывается с ярлыка «Генштаб», живёт в трее.")
    say("При первом запуске он заберёт данные Темпа (~/.tempo → ~/.genshtab) и развернёт кампанию-85.")
    say("Папку со сборкой build/ можно удалить, программе она не нужна.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
