/* haitun-updater.c - swap the install directory once the app processes exit.
 *
 * Invoked by psi-agent.exe self-update after staging is complete:
 *   haitun-updater.exe <install-dir> <staging-dir> <backup-dir> <updates-root>
 *
 * The bootstrap deliberately does no network and no verification; it only
 * waits for haitun.exe / psi-agent.exe, renames install -> backup and
 * staging -> install, records the new state, and relaunches haitun.exe.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#define MAX_PATH_BUF 4096
#define STATE_BUF 65536

static WCHAR g_log_path[MAX_PATH_BUF];

static void log_line(const char *msg)
{
    DWORD written = 0;
    HANDLE h = CreateFileW(g_log_path, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    WriteFile(h, msg, (DWORD)strlen(msg), &written, NULL);
    WriteFile(h, "\r\n", 2, &written, NULL);
    CloseHandle(h);
}

static int process_running(const WCHAR *name)
{
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe;
    int found = 0;
    if (snap == INVALID_HANDLE_VALUE)
        return 0;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (_wcsicmp(pe.szExeFile, name) == 0) {
                found = 1;
                break;
            }
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return found;
}

static int wait_process_exit(const WCHAR *name, DWORD timeout_ms)
{
    DWORD waited = 0;
    while (process_running(name)) {
        if (waited >= timeout_ms)
            return 0;
        Sleep(500);
        waited += 500;
    }
    return 1;
}

static int move_dir(const WCHAR *from, const WCHAR *to, int retries)
{
    int i;
    for (i = 0; i < retries; i++) {
        if (MoveFileExW(from, to,
                        MOVEFILE_WRITE_THROUGH | MOVEFILE_REPLACE_EXISTING))
            return 1;
        Sleep(1000);
    }
    return 0;
}

static void write_state_status(const WCHAR *root, const WCHAR *status)
{
    WCHAR path[MAX_PATH_BUF];
    WCHAR status_w[64];
    HANDLE h;
    DWORD written = 0;
    char utf8[128];
    char payload[256];
    int status_len;
    int payload_len;

    /* Rewrite the state file entirely. Parsing the existing JSON in C would
     * couple us to the Python writer's exact formatting; the updater only
     * needs the status field, and version comes from haitun-update.conf. */
    lstrcpynW(status_w, status, 64);
    wsprintfW(path, L"%s\\update-state.json", root);
    h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                    CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    status_len = WideCharToMultiByte(CP_UTF8, 0, status_w, -1, utf8,
                                     sizeof(utf8), NULL, NULL);
    if (status_len > 0) {
        payload_len = _snprintf(payload, sizeof(payload),
                                "{\n  \"status\": \"%s\"\n}\n", utf8);
        if (payload_len > 0)
            WriteFile(h, payload, (DWORD)payload_len, &written, NULL);
    }
    CloseHandle(h);
}

static void delete_swap_requested(const WCHAR *root)
{
    WCHAR path[MAX_PATH_BUF];
    wsprintfW(path, L"%s\\swap-requested.json", root);
    DeleteFileW(path);
}

static void write_cleanup_pending(const WCHAR *root, const WCHAR *backup)
{
    WCHAR path[MAX_PATH_BUF];
    HANDLE h;
    DWORD written = 0;
    char utf8[MAX_PATH_BUF];
    int len;

    wsprintfW(path, L"%s\\cleanup-pending.txt", root);
    h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                    CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    len = WideCharToMultiByte(CP_UTF8, 0, backup, -1, utf8, sizeof(utf8),
                              NULL, NULL);
    if (len > 1) {
        utf8[len - 1] = '\n';
        WriteFile(h, utf8, (DWORD)len, &written, NULL);
    }
    CloseHandle(h);
}

static void launch_haitun(const WCHAR *install)
{
    WCHAR cmd[MAX_PATH_BUF];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    wsprintfW(cmd, L"\"%s\\haitun.exe\"", install);
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOWNORMAL;
    ZeroMemory(&pi, sizeof(pi));
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, install,
                       &si, &pi)) {
        if (pi.hThread)
            CloseHandle(pi.hThread);
        if (pi.hProcess)
            CloseHandle(pi.hProcess);
    }
}

int WINAPI wmain(int argc, wchar_t *argv[])
{
    const WCHAR *install;
    const WCHAR *staging;
    const WCHAR *backup;
    const WCHAR *root;

    if (argc < 5)
        return 1;
    install = argv[1];
    staging = argv[2];
    backup = argv[3];
    root = argv[4];
    wsprintfW(g_log_path, L"%s\\updater.log", root);

    log_line("haitun-updater: start");
    if (!wait_process_exit(L"haitun.exe", 60000)) {
        log_line("haitun-updater: haitun.exe did not exit");
        write_state_status(root, L"failed");
        return 1;
    }
    if (!wait_process_exit(L"psi-agent.exe", 60000)) {
        log_line("haitun-updater: psi-agent.exe did not exit");
        write_state_status(root, L"failed");
        return 1;
    }

    if (!move_dir(install, backup, 3)) {
        log_line("haitun-updater: move install -> backup failed");
        write_state_status(root, L"failed");
        return 1;
    }
    if (!move_dir(staging, install, 3)) {
        log_line("haitun-updater: move staging -> install failed; rolling back");
        move_dir(backup, install, 3);
        write_state_status(root, L"failed");
        return 1;
    }

    write_state_status(root, L"applied");
    delete_swap_requested(root);
    write_cleanup_pending(root, backup);
    launch_haitun(install);
    log_line("haitun-updater: applied");
    return 0;
}
