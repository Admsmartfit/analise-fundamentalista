"""
Aplicador de atualização (roda FORA do servidor, só com a biblioteca padrão).

O servidor copia este arquivo para <dados>\\updates\\ e o executa como processo separado,
porque o servidor precisa ser parado para o código ser trocado. Passos:

 1. Espera o servidor responder ao clique e encerra o processo dele.
 2. Extrai o pacote em <raiz>\\app_new e valida (VERSION, main.py, src\\).
 3. Se requirements.txt mudou, instala as dependências novas no runtime embutido.
 4. Troca as pastas: app -> app_old, app_new -> app.
 5. Sobe o servidor e espera /api/health responder com a versão nova.
 6. Se algo falhar: volta app_old -> app, sobe a versão anterior (rollback).

O resultado fica em <dados>\\updates\\last_result.json e o log em <dados>\\logs\\update.log.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


class Updater:
    def __init__(self, root: Path, data_dir: Path, zip_path: Path, pid: int, port: int):
        self.root = root
        self.data_dir = data_dir
        self.zip_path = zip_path
        self.pid = pid
        self.port = port
        self.app = root / "app"
        self.app_new = root / "app_new"
        self.app_old = root / "app_old"
        self.python = root / "runtime" / "python.exe"
        self.pythonw = root / "runtime" / "pythonw.exe"
        (data_dir / "logs").mkdir(parents=True, exist_ok=True)
        (data_dir / "updates").mkdir(parents=True, exist_ok=True)
        self.log_file = data_dir / "logs" / "update.log"
        self.status_file = data_dir / "updates" / "status.json"
        self.result_file = data_dir / "updates" / "last_result.json"

    # ---------- utilidades ----------
    def log(self, msg: str):
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def status(self, fase: str, mensagem: str):
        self.log(f"{fase}: {mensagem}")
        self.status_file.write_text(json.dumps({"fase": fase, "mensagem": mensagem,
                                                "quando": datetime.datetime.now().isoformat()},
                                               ensure_ascii=False), encoding="utf-8")

    def health_version(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=3) as r:
                return json.loads(r.read().decode("utf-8")).get("version")
        except Exception:
            return None

    def read_version(self, app_dir: Path) -> str:
        f = app_dir / "VERSION"
        return f.read_text(encoding="utf-8").strip() if f.exists() else "?"

    def stop_server(self):
        subprocess.run(["taskkill", "/PID", str(self.pid), "/F"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
        pid_file = self.data_dir / "server.pid"
        if pid_file.exists():
            try:
                other = int(pid_file.read_text().strip())
                if other != self.pid:
                    subprocess.run(["taskkill", "/PID", str(other), "/F"],
                                   capture_output=True, creationflags=CREATE_NO_WINDOW)
            except ValueError:
                pass
        for _ in range(60):  # espera a porta liberar
            if self.health_version() is None:
                return
            time.sleep(0.5)
        raise RuntimeError("O servidor antigo não encerrou.")

    def start_server(self):
        launcher = self.app / "launcher.py"
        env = dict(os.environ, TA_DATA_DIR=str(self.data_dir))
        self.launcher_proc = subprocess.Popen(
            [str(self.pythonw), str(launcher), "--background"], cwd=str(self.root), env=env,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)

    def wait_healthy(self, expected: str, timeout: int = 120) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            v = self.health_version()
            if v == expected:
                return True
            # O launcher sai com código != 0 quando o servidor morre ao iniciar: não espera à toa
            proc = getattr(self, "launcher_proc", None)
            if proc is not None and proc.poll() not in (None, 0):
                return False
            time.sleep(2)
        return False

    def move_with_retry(self, src: Path, dst: Path):
        for i in range(20):  # antivírus/indexador às vezes seguram arquivos por instantes
            try:
                src.rename(dst)
                return
            except PermissionError:
                time.sleep(1)
        src.rename(dst)

    def rmtree(self, p: Path):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    def result(self, ok: bool, de: str, para: str, mensagem: str):
        self.result_file.write_text(json.dumps({
            "ok": ok, "de": de, "para": para, "mensagem": mensagem,
            "quando": datetime.datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False), encoding="utf-8")
        self.status("concluido" if ok else "falhou", mensagem)

    # ---------- fluxo ----------
    def run(self):
        de = self.read_version(self.app)
        para = "?"
        trocou = False
        try:
            self.status("preparando", "Validando pacote de atualização...")
            self.rmtree(self.app_new)
            with zipfile.ZipFile(self.zip_path) as z:
                z.extractall(self.app_new)
            for obrigatorio in ("VERSION", "main.py", "launcher.py", "src"):
                if not (self.app_new / obrigatorio).exists():
                    raise RuntimeError(f"Pacote inválido: falta '{obrigatorio}'.")
            para = self.read_version(self.app_new)

            time.sleep(2)  # deixa o servidor responder ao clique antes de encerrar
            self.status("parando", "Parando o servidor...")
            self.stop_server()

            req_old = (self.app / "requirements.txt").read_text(encoding="utf-8") if (self.app / "requirements.txt").exists() else ""
            req_new = (self.app_new / "requirements.txt").read_text(encoding="utf-8")
            if req_old.strip() != req_new.strip():
                self.status("dependencias", "Instalando dependências novas (precisa de internet)...")
                r = subprocess.run([str(self.python), "-m", "pip", "install", "--no-warn-script-location",
                                    "--disable-pip-version-check", "-r", str(self.app_new / "requirements.txt")],
                                   capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                self.log(r.stdout[-4000:])
                if r.returncode != 0:
                    self.log(r.stderr[-4000:])
                    raise RuntimeError("Falha ao instalar dependências (veja logs\\update.log).")

            self.status("trocando", f"Instalando versão {para}...")
            self.rmtree(self.app_old)
            self.move_with_retry(self.app, self.app_old)
            self.move_with_retry(self.app_new, self.app)
            trocou = True

            self.status("iniciando", f"Iniciando versão {para}...")
            self.start_server()
            if not self.wait_healthy(para):
                raise RuntimeError(f"A versão {para} não conseguiu iniciar (veja logs\\server.log).")

            self.result(True, de, para, f"Atualizado de {de} para {para}.")
        except Exception as e:
            self.log(f"ERRO: {e!r}")
            try:
                if trocou and self.app_old.exists():
                    self.status("revertendo", f"Falhou ({e}). Voltando para a versão {de}...")
                    self._kill_by_pidfile()
                    self.rmtree(self.root / "app_failed")
                    self.move_with_retry(self.app, self.root / "app_failed")
                    self.move_with_retry(self.app_old, self.app)
                if self.health_version() is None:
                    self.start_server()
                    self.wait_healthy(de, timeout=90)
            finally:
                self.result(False, de, para, f"Atualização para {para} falhou e o sistema voltou para {de}: {e}")
        finally:
            self.rmtree(self.app_new)

    def _kill_by_pidfile(self):
        pid_file = self.data_dir / "server.pid"
        if pid_file.exists():
            try:
                subprocess.run(["taskkill", "/PID", pid_file.read_text().strip(), "/F"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
        for _ in range(30):
            if self.health_version() is None:
                return
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--zip", required=True)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    Updater(Path(a.root), Path(a.data_dir), Path(a.zip), a.pid, a.port).run()


if __name__ == "__main__":
    main()
