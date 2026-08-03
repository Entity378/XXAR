using System;
using System.Linq;
using System.Windows;

using XXAR.Wizard;

namespace XXAR.Setup
{
    public partial class App : Application
    {
        private static readonly string[] SilentSwitches = { "/silent", "/verysilent", "/s" };

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
                }
                else if (session.RemoveOnly)
                {
                    session.PurgeUserData = purge;
                    RemoveJob.Run(session, progress: null);
                }
                else
                {
                    InstallJob.Run(session, progress: null, cancel: System.Threading.CancellationToken.None);
                }
                return 0;
            }
            catch (Exception ex)
            {
                Journal.Error("silent run failed", ex);
                return 1;
            }
        }
    }
}
