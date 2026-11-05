// Likho.app's main executable: a tiny Cocoa app that runs the Python app as its CHILD.
//
// Why a child (not exec): macOS attributes a child's privacy permissions (Microphone, Input
// Monitoring, Accessibility) to the parent app, so they're checked against "Likho". exec'ing Python
// would make macOS check "python3.12" instead.
//
// Why Cocoa: clicking Likho in Finder/Spotlight while it's running sends a "reopen" event; we
// answer it by asking the Python app to show the dashboard (POST /api/show on the local server).
//
// Built by scripts/build_app.sh with -DPROJECT="..." -DPYTHON="...".
#import <Cocoa/Cocoa.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>

extern char **environ;

@interface Launcher : NSObject <NSApplicationDelegate>
@end

@implementation Launcher {
    pid_t _child;
    BOOL _atLogin;
    dispatch_source_t _exitWatch;
}

- (void)applicationWillFinishLaunching:(NSNotification *)note {
    // Started by Login Items? Then stay quiet in the menu bar instead of opening the dashboard.
    NSAppleEventDescriptor *ev = [[NSAppleEventManager sharedAppleEventManager] currentAppleEvent];
    _atLogin = ev.eventID == kAEOpenApplication &&
               [ev paramDescriptorForKeyword:keyAEPropData].enumCodeValue == keyAELaunchedAsLogInItem;
}

- (void)applicationDidFinishLaunching:(NSNotification *)note {
    NSString *log = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Likho.log"];
    if (chdir(PROJECT) != 0) {
        [self fail:@"Can't find the Likho project folder. Rebuild the app with scripts/build_app.sh."];
        return;
    }
    setenv("LIKHO_LAUNCHER", "1", 1);
    if (!_atLogin) setenv("LIKHO_SHOW_DASHBOARD", "1", 1);

    posix_spawn_file_actions_t files;
    posix_spawn_file_actions_init(&files);
    posix_spawn_file_actions_addopen(&files, STDOUT_FILENO, log.fileSystemRepresentation,
                                     O_WRONLY | O_CREAT | O_APPEND, 0644);
    posix_spawn_file_actions_adddup2(&files, STDOUT_FILENO, STDERR_FILENO);
    char *argv[] = {PYTHON, "-m", "likho", NULL};
    if (posix_spawn(&_child, PYTHON, &files, NULL, argv, environ) != 0) {
        [self fail:@"Can't start Python. Run ./run.sh once in the project folder, then try again."];
        return;
    }

    // When the Python app exits (Quit Likho from the menu bar), quit the launcher too.
    _exitWatch = dispatch_source_create(DISPATCH_SOURCE_TYPE_PROC, _child, DISPATCH_PROC_EXIT,
                                        dispatch_get_main_queue());
    dispatch_source_set_event_handler(_exitWatch, ^{
      int status;
      waitpid(self->_child, &status, 0);
      self->_child = 0;
      [NSApp terminate:nil];
    });
    dispatch_resume(_exitWatch);
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)flag {
    [self showDashboard];
    return NO;
}

- (void)showDashboard {
    if (@available(macOS 14.0, *)) {
        NSRunningApplication *py = [NSRunningApplication runningApplicationWithProcessIdentifier:_child];
        if (py) [NSApp yieldActivationToApplication:py];  // let the Python app bring its window forward
    }
    const char *port = getenv("LIKHO_PORT");
    NSString *url = [NSString stringWithFormat:@"http://127.0.0.1:%s/api/show", port ? port : "8765"];
    NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:url]];
    req.HTTPMethod = @"POST";
    [req setValue:@"1" forHTTPHeaderField:@"X-Likho"];
    [[[NSURLSession sharedSession] dataTaskWithRequest:req] resume];
}

- (void)applicationWillTerminate:(NSNotification *)note {
    if (_child > 0) kill(_child, SIGTERM);
}

- (void)fail:(NSString *)message {
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"Likho couldn't start";
    alert.informativeText = message;
    [NSApp activateIgnoringOtherApps:YES];
    [alert runModal];
    [NSApp terminate:nil];
}
@end

int main(void) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        Launcher *delegate = [Launcher new];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
