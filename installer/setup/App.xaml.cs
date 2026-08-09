using System;
using System.Linq;
using System.Threading;
using System.Windows;

using XXAR.Wizard;

namespace XXAR.Setup
{
    public partial class App : Application
    {
        private static readonly string[] SilentSwitches = { "/silent", "/verysilent", "/s" };

        // The app's updater launches us and only then quits, so its files are still locked for a moment.
        private static readonly TimeSpan ShutdownGrace = TimeSpan.FromSeconds(60);

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            Journal.Start("XXAR-Installer.log", "XXAR Installer log");

            var switches = e.Args.Select(argument => argument.ToLowerInvariant()).ToArray();
            var session = SetupSession.Start(forceRemove: switches.Contains("/uninstall"));

            if (switches.Any(SilentSwitches.Contains))
            {
                Shutdown(RunSilently(session, purge: switches.Contains("/purge")));
                return;
            }

            var window = new MainWindow(session);
            MainWindow = window;
            window.Show();
        }

        // Used by the app's own updater; 0 means it worked, 1 means look in the log.
        private static int RunSilently(SetupSession session, bool purge)
        {
            try
            {
                if (session.RemoveOnly && !session.Machine.IsInstalled)
                {
                    Journal.Info("nothing to uninstall");
                    return 0;
                }

                WaitForAppToClose(session.Machine.InstalledRoot);

                if (session.RemoveOnly)
                {
                    session.PurgeUserData = purge;
                    RemoveJob.Run(session, progress: null);
                }
                else
                {
                    InstallJob.Run(session, progress: null, cancel: CancellationToken.None);
                }
                return 0;
            }
            catch (Exception ex)
            {
                Journal.Error("silent run failed", ex);
                return 1;
            }
        }

        private static void WaitForAppToClose(string installedRoot)
        {
            if (installedRoot == null) return;

            var launcher = InstallLocations.LauncherIn(installedRoot);
            var giveUpAt = DateTime.UtcNow + ShutdownGrace;
            if (!AppLock.IsRunning(launcher)) return;

            Journal.Info("waiting for XXAR to close");
            while (AppLock.IsRunning(launcher) && DateTime.UtcNow < giveUpAt)
                Thread.Sleep(500);

            // Still locked means the job below throws AppRunningException, which the caller logs.
            Journal.Info(AppLock.IsRunning(launcher) ? "XXAR is still running" : "XXAR closed");
        }
    }
}
