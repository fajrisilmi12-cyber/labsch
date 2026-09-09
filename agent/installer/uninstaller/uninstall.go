//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"unsafe"
)

const (
	appDir = `C:\ProgramData\LabSCHAgent`
)

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
		0,
		1,
	)
	os.Exit(0)
}

func runCmd(name string, args ...string) bool {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run() == nil
}

func main() {
	if !isAdmin() {
		elevateAndRerun()
		return
	}

	fmt.Println()
	fmt.Println("================================================================")
	fmt.Println("  LabSCHAgent Uninstaller")
	fmt.Println("================================================================")
	fmt.Println()

	// 1. Remove scheduled tasks
	fmt.Print("[1/5] Removing scheduled tasks... ")
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentWatchdog", "/f")
	runCmd("schtasks", "/delete", "/tn", "LabSCHAgentOnBoot", "/f")
	fmt.Println("OK")

	// 2. Remove Run key
	fmt.Print("[2/5] Removing Run key... ")
	runCmd("reg", "delete",
		`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`,
		"/v", "LabSCHAgent", "/f")
	fmt.Println("OK")

	// 3. Re-enable Task Manager
	fmt.Print("[3/5] Re-enabling Task Manager... ")
	runCmd("reg", "delete",
		`HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`,
		"/v", "DisableTaskMgr", "/f")
	fmt.Println("OK")

	// 4. Kill agent processes
	fmt.Print("[4/5] Stopping agent processes... ")
	agentProc := exec.Command("taskkill", "/f", "/im", "python.exe", "/fi", "WINDOWTITLE eq labsch_agent*")
	agentProc.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	agentProc.Run()
	fmt.Println("OK")

	// 5. Remove files
	fmt.Print("[5/5] Removing config and agent files... ")
	if _, err := os.Stat(appDir); err == nil {
		os.RemoveAll(appDir)
	}
	fmt.Println("OK")

	fmt.Println()
	fmt.Println("================================================================")
	fmt.Println("  UNINSTALL SELESAI")
	fmt.Println("================================================================")
	fmt.Println()
	fmt.Println("Yang sudah dihapus:")
	fmt.Println("  - Scheduled task: LabSCHAgentWatchdog")
	fmt.Println("  - Scheduled task: LabSCHAgentOnBoot")
	fmt.Println("  - Run key: LabSCHAgent")
	fmt.Println("  - Task Manager: re-enabled")
	fmt.Println("  - Config + agent files:", appDir)
	fmt.Println()
	fmt.Println("Tekan Enter untuk keluar...")
	fmt.Scanln()
}
