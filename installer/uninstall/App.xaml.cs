using System;
using System.Linq;
using System.Windows;
using XXAR.Wizard;

namespace XXAR.Uninstall
{
    public partial class App : Application
    {
        private static readonly string[] SilentSwitches = { "/silent", "/verysilent", "/s" };

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            Journal.Start("XXAR-Uninstall.log", "XXAR uninstall log");

            var switches = e.Args.Select(argument => argument.ToLowerInvariant()).ToArray();
            var plan = RemovalPlan.Build();

            if (switches.Any(SilentSwitches.Contains))
            {
                Shutdown(RunSilently(plan, purge: switches.Contains("/purge")));
                return;
            }

            var window = new MainWindow(plan);
            MainWindow = window;
            window.Show();
        }

        // Exists for scripted removal; 0 means it worked, 1 means look in the log.
        private static int RunSilently(RemovalPlan plan, bool purge)
        {
            try
            {
                if (!plan.IsInstalled)
                {
                    Journal.Info("nothing to remove");
                }
                else
                {
                    plan.UserData.Selected = purge;
                    RemovalJob.Run(plan, progress: null);
                }
                return 0;
            }
            catch (Exception ex)
            {
                Journal.Error("silent uninstall failed", ex);
                return 1;
            }
        }
    }
}
