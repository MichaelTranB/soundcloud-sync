// Crate Helper: starts The Crate's own jobs as its children, so the one macOS permission given to it
// (Full Disk Access, which lets yt-dlp read the SoundCloud sign-in already in Chrome or Safari) covers
// those jobs and nothing else. It only runs the three jobs below, from the folder it sits in.
// install.sh builds it into "Crate Helper.app" and the background jobs start through it.
//
//   crate-helper app    the page (python3 app.py)
//   crate-helper sync   the sync (sync.sh)
//   crate-helper usb    the copy to the USB (usb.sh)
#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: crate-helper app|sync|usb\n");
        return 64;
    }
    // The app folder: this file is <dir>/Crate Helper.app/Contents/MacOS/crate-helper.
    char raw[PATH_MAX], self[PATH_MAX], dir[PATH_MAX];
    uint32_t size = sizeof raw;
    if (_NSGetExecutablePath(raw, &size) != 0 || !realpath(raw, self)) {
        fprintf(stderr, "crate-helper: cannot find its own path\n");
        return 70;
    }
    strlcpy(dir, self, sizeof dir);
    for (int i = 0; i < 4; i++) strlcpy(dir, dirname(dir), sizeof dir);

    char target[PATH_MAX];
    char *args[3] = {0};
    if (strcmp(argv[1], "app") == 0) {
        snprintf(target, sizeof target, "%s/app.py", dir);
        // Homebrew's Python (Apple chip, then Intel), else the one Apple's command line tools put in.
        const char *py[] = {"/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"};
        args[0] = (char *)py[2];
        for (int i = 0; i < 3; i++)
            if (access(py[i], X_OK) == 0) { args[0] = (char *)py[i]; break; }
        args[1] = target;
    } else if (strcmp(argv[1], "sync") == 0 || strcmp(argv[1], "usb") == 0) {
        snprintf(target, sizeof target, "%s/%s.sh", dir, argv[1]);
        args[0] = target;
    } else {
        fprintf(stderr, "crate-helper: unknown job '%s' (app, sync or usb)\n", argv[1]);
        return 64;
    }

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    int err = posix_spawn(&child, args[0], NULL, NULL, args, environ);
    if (err) {
        fprintf(stderr, "crate-helper: cannot start %s: %s\n", args[0], strerror(err));
        return 127;
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return 71;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
