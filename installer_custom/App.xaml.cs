using System;
using System.Linq;
using System.Windows;

namespace XXAR.Setup
{
    public partial class App : Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);

            var args = e.Args.Select(a => a.ToLowerInvariant()).ToArray();
            var ctx = SetupContext.Detect(forceUninstall: args.Contains("/uninstall"));

            // Silent modes exist for the in-app updater; exit code 0 = ok, 1 = failure.
            if (args.Contains("/silent") || args.Contains("/verysilent") || args.Contains("/s"))
            {
                int code;
                try
                {
                    if (ctx.UninstallOnly && !ctx.IsInstalled)
                        SetupLog.Info("nothing to uninstall");
                    else if (ctx.UninstallOnly)
                        SetupEngine.Uninstall(ctx, purgeUserData: args.Contains("/purge"), progress: null);
                    else
                        SetupEngine.Install(ctx, progress: null, ct: System.Threading.CancellationToken.None);
                    code = 0;
                }
                catch (Exception ex)
                {
                    SetupLog.Error("silent run failed", ex);
                    code = 1;
                }
                Shutdown(code);
                return;
            }

            var window = new MainWindow(ctx);
            MainWindow = window;
            window.Show();
        }
    }
}
