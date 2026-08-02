using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public partial class ProgressPage : UserControl
    {
        private readonly MainWindow host;
        private readonly bool uninstalling;
        private readonly CancellationTokenSource cts = new CancellationTokenSource();
        private bool started;

        public ProgressPage(MainWindow host, bool uninstalling)
        {
            this.host = host;
            this.uninstalling = uninstalling;
            InitializeComponent();
            if (uninstalling)
            {
                DialogTitleLabel.Text = "Removing XXAR";
                DialogDescription.Text = "Please wait while the Setup Wizard removes XXAR.";
                // Uninstall is quick and has no rollback; a mid-flight cancel would only leave a half-removed install.
                Cancel.IsEnabled = false;
            }
        }

        private async void Page_Loaded(object sender, RoutedEventArgs e)
        {
            if (started) return;
            started = true;

            var progress = new Progress<(int pct, string status)>(p =>
            {
                Progress.Value = p.pct;
                CurrentAction.Text = p.status;
            });

            while (true)
            {
                try
                {
                    await Task.Run(() =>
                    {
                        if (uninstalling)
                            SetupEngine.Uninstall(host.Ctx, host.Ctx.PurgeUserData, progress);
                        else
                            SetupEngine.Install(host.Ctx, progress, cts.Token);
                    });
                    host.Go(new ExitPage(host, ExitOutcome.Success, uninstalling));
                    return;
                }
                catch (AppRunningException)
                {
                    var choice = MessageBox.Show(Window.GetWindow(this),
                        "XXAR is currently running.\n\nClose it, then click Retry to continue.",
                        "XXAR Setup", MessageBoxButton.OKCancel, MessageBoxImage.Warning);
                    if (choice == MessageBoxResult.OK) continue;
                    host.Go(new ExitPage(host, ExitOutcome.Cancelled, uninstalling));
                    return;
                }
                catch (OperationCanceledException)
                {
                    host.Go(new ExitPage(host, ExitOutcome.Cancelled, uninstalling));
                    return;
                }
                catch (Exception ex)
                {
                    SetupLog.Error(uninstalling ? "uninstall failed" : "install failed", ex);
                    host.Ctx.FailureText = ex.Message;
                    host.Go(new ExitPage(host, ExitOutcome.Failed, uninstalling));
                    return;
                }
            }
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            // Immediate feedback — the running operation stops at the next file boundary.
            Cancel.IsEnabled = false;
            CurrentAction.Text = "Canceling…";
            cts.Cancel();
        }
    }
}
