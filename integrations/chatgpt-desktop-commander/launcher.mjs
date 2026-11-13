import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const desktopCommanderRoot = "C:\\CreoDevo\\.AI\\DesktopCommanderMCP";
const desktopCommanderEntry = path.join(desktopCommanderRoot, "dist", "index.js");
const profileRoot = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
  "SF2AiS",
  "ChatGPTDesktopPluginProfile"
);
const configDirectory = path.join(profileRoot, ".claude-server-commander");
const configPath = path.join(configDirectory, "config.json");

const restrictedConfig = {
  allowedDirectories: ["C:\\CreoDevo"],
  telemetryEnabled: false,
  blockedCommands: [
    "format", "mount", "umount", "mkfs", "fdisk", "dd",
    "sudo", "su", "passwd", "adduser", "useradd", "usermod", "groupadd"
  ]
};

function stop(message) {
  process.stderr.write("[SF2AiS Desktop Access] " + message + "\n");
  process.exit(1);
}

if (!fs.existsSync(desktopCommanderEntry)) {
  stop("Desktop Commander was not found at " + desktopCommanderEntry);
}

fs.mkdirSync(configDirectory, { recursive: true });
if (!fs.existsSync(configPath)) {
  fs.writeFileSync(configPath, JSON.stringify(restrictedConfig, null, 2) + "\n", { flag: "wx" });
} else {
  let existing;
  try {
    existing = JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch {
    stop("The dedicated Desktop Commander profile config is unreadable; refusing to start.");
  }
  if (
    !Array.isArray(existing.allowedDirectories) ||
    existing.allowedDirectories.length !== 1 ||
    path.resolve(existing.allowedDirectories[0]).toLowerCase() !== path.resolve("C:\\CreoDevo").toLowerCase() ||
    existing.telemetryEnabled !== false
  ) {
    stop("The dedicated profile must keep allowedDirectories=[C:\\CreoDevo] and telemetryEnabled=false.");
  }
}

const env = { ...process.env, USERPROFILE: profileRoot };
const child = spawn(process.execPath, [desktopCommanderEntry, "--no-onboarding"], {
  cwd: desktopCommanderRoot,
  env,
  stdio: "inherit",
  windowsHide: true
});

child.on("error", (error) => stop("Could not start Desktop Commander: " + error.message));
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}
child.on("exit", (code) => process.exit(code ?? 1));
