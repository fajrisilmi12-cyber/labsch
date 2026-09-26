//go:build windows

package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

//go:embed agent/*
var agentFS embed.FS

const (
	appDir = `C:\ProgramData\LabSCHAgent`
	// Build-time placeholders. Replace only in a private release build;
	// never commit or publish a real deployment URL or API token.
	serverURL = `https://labsch-api.<your-subdomain>.workers.dev`
	token     = `<your-api-token>`
)

const version = `0.4.1`

func isAdmin() bool {
	cmd := exec.Command("net", "session")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run() == nil
}

func elevateAndRerun() {
	exe, _ := os.Executable()
	verb, _ := syscall.UTF16PtrFromString("runas")
	app, _ := syscall.UTF16PtrFromString(exe)
	arg, _ := syscall.UTF16PtrFromString("--elevated")
	syscall.SyscallN(
		syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW").Addr(),
		0,
		uintptr(unsafe.Pointer(verb)),
		uintptr(unsafe.Pointer(app)),
		uintptr(unsafe.Pointer(arg)),
		0, 1,
	)
	os.Exit(0)
}

func readInput(prompt string) string {
	fmt.Print(prompt)
	var s string
	fmt.Scanln(&s)
	return s
}

func runCmd(name string, args ...string) bool {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run() == nil
}

func runCmdOutput(name string, args ...string) string {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, _ := cmd.CombinedOutput()
	return string(out)
}

func verifyInstalledVersion(configPath, want string) bool {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return false
	}
	var cfg map[string]any
	if json.Unmarshal(data, &cfg) != nil {
		return false
	}
	got, _ := cfg["version"].(string)
	return got == want
}

func verifyEmbeddedPayloadVersion(agentPath, want string) bool {
	data, err := os.ReadFile(agentPath)
	return err == nil && strings.Contains(string(data), want)
}

func printBanner() {
	fmt.Println()
	fmt.Println("================================================================")
	fmt.Printf("  LabSCHAgent Installer v%s\n", version)
	fmt.Println("  School Lab Computer Manager")
	fmt.Println("================================================================")
	fmt.Println()
}

func main() {
	if strings.Contains(serverURL, "<your-subdomain>") || strings.HasPrefix(token, "<") {
		fmt.Println("ERROR: installer masih memakai placeholder server/token.")
		fmt.Println("Buat private release build dengan kredensial deployment Anda.")
		return
	}
	if !isAdmin() {
		elevateAndRerun()
		return
	}

	printBanner()

	// Stop every startup source before killing processes, otherwise the old
	// scheduled task can respawn test7 while test8 is being installed.
	fmt.Print("[0/7] Stopping old agent and startup task... ")
	runCmd("schtasks", "/end", "/tn", "LabSCHAgentOnBoot")
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentWatchdog", "/f")
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentOnBoot", "/f")
	runCmd("reg", "delete", `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`, "/v", "LabSCHAgent", "/f")
	killOldAgents()
	fmt.Println("OK")

	// Display name
	fmt.Println("Masukkan nama PC ini.")
	fmt.Println("  Contoh: PC-LAB-01, PC-GURU, PC-TEST")
	fmt.Println("  (Kosongkan untuk otomatis pakai hostname)")
	fmt.Println()
	displayName := readInput("Nama PC: ")
	if displayName == "" {
		hostname, _ := os.Hostname()
		displayName = "PC-" + hostname
	}
	fmt.Printf("Nama PC: %s\n\n", displayName)

	// Test PC
	fmt.Print("PC testing/development? [y/N]: ")
	var isTest string
	fmt.Scanln(&isTest)
	testFlag := "false"
	if strings.ToLower(isTest) == "y" {
		testFlag = "true"
	}
	fmt.Printf("Test PC: %s\n\n", testFlag)

	// 2. Resolve Python to an absolute executable path. Scheduled tasks run
	// as SYSTEM and must not depend on the interactive user's PATH.
	fmt.Print("[1/7] Checking Python... ")
	pythonExe := ""
	for _, py := range []string{"python", "python3"} {
		candidate, err := exec.LookPath(py)
		if err == nil && runCmd(candidate, "--version") {
			pythonExe, _ = filepath.Abs(candidate)
			break
		}
	}
	if pythonExe == "" {
		fmt.Println("FAILED")
		fmt.Println("\nERROR: Python tidak ditemukan!")
		fmt.Println("Install Python 3.10+ dari python.org")
		fmt.Println("JANGAN LUPA centang 'Add Python to PATH' saat install.")
		fmt.Scanln()
		return
	}
	fmt.Println("OK")

	// 3. Install deps with better handling
	fmt.Print("[2/7] Installing dependencies... ")
	for _, py := range []string{"python", "python3"} {
		cmd := exec.Command(py, "-m", "pip", "install", "psutil", "requests")
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		if cmd.Run() == nil {
			break
		}
		// Try --user flag
		cmd2 := exec.Command(py, "-m", "pip", "install", "--user", "psutil", "requests")
		cmd2.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		cmd2.Run()
	}
	// Verify psutil
	verifyPSutil := runCmd("python", "-c", "import psutil")
	if !verifyPSutil {
		verifyPSutil = runCmd("python3", "-c", "import psutil")
	}
	if verifyPSutil {
		fmt.Println("OK")
	} else {
		fmt.Println("WARNING: psutil might not be installed. Agent will work but app-blocking may fail.")
	}

	// 4. Write config (PRESERVE existing client_id!)
	fmt.Print("[3/7] Writing config... ")
	os.MkdirAll(appDir, 0755)
	configPath := filepath.Join(appDir, "config.ini")

	// Read existing config to preserve client_id
	existingClientID := ""
	if data, err := os.ReadFile(configPath); err == nil {
		content := string(data)
		// Extract client_id from existing config
		if idx := strings.Index(content, `"client_id"`); idx != -1 {
			rest := content[idx:]
			if start := strings.Index(rest, `"`); start != -1 {
				rest = rest[start+1:]
				if end := strings.Index(rest, `"`); end != -1 {
					existingClientID = rest[:end]
				}
			}
		}
	}

	cfg := fmt.Sprintf(`{
  "server_url": "%s",
  "api_token": "%s",
  "client_id": "%s",
  "display_name": "%s",
  "is_test": %s,
  "version": "%s"
}`, serverURL, token, existingClientID, displayName, testFlag, version)
	if err := os.WriteFile(configPath, []byte(cfg), 0644); err != nil || !verifyInstalledVersion(configPath, version) {
		fmt.Println("FAILED")
		fmt.Println("CONFIG VERSION VERIFICATION FAILED - agent lama tidak akan dijalankan.")
		return
	}
	if existingClientID != "" {
		fmt.Printf("OK (preserved client_id: %s)\n", existingClientID)
	} else {
		fmt.Println("OK (new client_id)")
	}

	// 5. Extract agent files
	fmt.Print("[4/7] Extracting agent files... ")
	entries, err := agentFS.ReadDir("agent")
	if err != nil {
		fmt.Println("FAILED")
		fmt.Println("PAYLOAD READ FAILED:", err)
		return
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		data, readErr := agentFS.ReadFile("agent/" + e.Name())
		if readErr != nil {
			fmt.Println("FAILED")
			fmt.Println("PAYLOAD READ FAILED:", e.Name(), readErr)
			return
		}
		if writeErr := os.WriteFile(filepath.Join(appDir, e.Name()), data, 0644); writeErr != nil {
			fmt.Println("FAILED")
			fmt.Println("PAYLOAD WRITE FAILED:", e.Name(), writeErr)
			return
		}
	}
	agentPath := filepath.Join(appDir, "labsch_agent.py")
	if !verifyEmbeddedPayloadVersion(agentPath, version) {
		fmt.Println("FAILED")
		fmt.Println("PAYLOAD VERSION VERIFICATION FAILED - agent lama tidak akan dijalankan.")
		return
	}
	fmt.Println("OK")

	// 6. Install self-protection (scheduled task only, NO Run key)
	fmt.Print("[5/7] Installing self-protection... ")

	// Remove ALL old tasks and Run key
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentWatchdog", "/f")
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentOnBoot", "/f")
	runCmd("reg", "delete",
		`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`,
		"/v", "LabSCHAgent", "/f")

	// One continuous SYSTEM task at boot. --once is intentionally forbidden:
	// it sends one heartbeat and exits, leaving the PC offline after restart.
	// A second periodic task is also forbidden because it can race this task.
	trBoot := fmt.Sprintf(`"%s" "%s"`, pythonExe, agentPath)
	if !runCmd("schtasks", "/create", "/tn", "LabSCHAgentOnBoot",
		"/tr", trBoot, "/sc", "onstart",
		"/ru", "SYSTEM", "/rl", "HIGHEST", "/f") {
		fmt.Println("FAILED")
		fmt.Println("ERROR: Tidak bisa membuat task startup LabSCHAgentOnBoot.")
		return
	}

	// NO Run key - agent only runs via the single scheduled task (SYSTEM)
	fmt.Println("OK")

	// 7. Disable Task Manager
	fmt.Print("[6/7] Disabling Task Manager... ")
	runCmd("reg", "add",
		`HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`,
		"/v", "DisableTaskMgr", "/t", "REG_DWORD", "/d", "1", "/f")
	fmt.Println("OK")

	// 8. Test heartbeat with the same absolute Python used by the SYSTEM task.
	fmt.Print("[7/7] Testing connection... ")
	cmd := exec.Command(pythonExe, agentPath, "--once")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if cmd.Run() == nil {
		fmt.Println("OK - KONEKSI BERHASIL")
	} else {
		fmt.Println("WARNING: Gagal connect. Agent tetap terinstall.")
	}

	fmt.Println()
	fmt.Println("================================================================")
	fmt.Println("  INSTALASI SELESAI")
	fmt.Println("================================================================")
	fmt.Printf("  Nama PC      : %s\n", displayName)
	fmt.Printf("  Test PC      : %s\n", testFlag)
	fmt.Println("  Agent dir    :", appDir)
	fmt.Println("  Scheduled    : LabSCHAgentOnBoot (continuous, SYSTEM)")
	fmt.Println("  Run key      : REMOVED (single startup path)")
	fmt.Println("  Task Manager : disabled")
	fmt.Println()
	fmt.Println("Agent berjalan kontinu sebagai SYSTEM dan mulai otomatis saat boot.")
	fmt.Println("Untuk uninstall: jalankan uninstall.exe")
	fmt.Println()

	fmt.Print("Start agent sekarang? [Y/n]: ")
	var ch string
	fmt.Scanln(&ch)
	if ch != "n" && ch != "N" {
		fmt.Println("Starting agent via scheduled task...")
		if runCmd("schtasks", "/run", "/tn", "LabSCHAgentOnBoot") {
			fmt.Println("OK: Agent berjalan tersembunyi sebagai SYSTEM dan tidak membuka window.")
			fmt.Println("Heartbeat akan terlihat di server dalam maksimal 30 detik.")
		} else {
			fmt.Println("GAGAL menjalankan task LabSCHAgentOnBoot.")
			fmt.Println("Cek Task Scheduler atau jalankan setup.exe lagi sebagai Administrator.")
		}
	}
}

func killOldAgents() {
	// Kill any running python agents
	for _, proc := range []string{"python.exe", "python3.exe", "pythonw.exe"} {
		cmd := exec.Command("taskkill", "/f", "/im", proc)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		cmd.Run()
	}
}
