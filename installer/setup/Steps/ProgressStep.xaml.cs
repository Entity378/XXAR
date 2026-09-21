using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class ProgressStep : UserControl
    {
        private readonly MainWindow wizard;
        private readonly bool removing;
        private readonly bool updating;
        private readonly CancellationTokenSource cancel = new CancellationTokenSource();
        private bool alreadyRan;

        public ProgressStep(MainWindow wizard, bool removing, bool updating = false)
        {
            this.wizard = wizard;
            this.removing = removing;
            this.updating = updating;
            InitializeComponent();

            if (removing)
            {
                Frame.Heading = "Removing XXAR";
                Frame.Subheading = "Please wait while XXAR is removed from your computer.";
                // Removal is quick and has no rollback; cancelling midway would only leave it half done.
                Cancel.IsEnabled = false;
            }

            if (updating)
            {
                Frame.Heading = "Updating XXAR";
                Frame.Subheading = "Please wait while XXAR is updated. It will restart when done.";
                // The user already chose to update from the app, so the run goes to the end.
                Cancel.IsEnabled = false;
            }
        }

        private async void Step_Loaded(object sender, RoutedEventArgs e)
        {
            if (alreadyRan) return;
            alreadyRan = true;

            var progress = new Progress<StepProgress>(step =>
            {
                Bar.Value = step.Percent;
                CurrentAction.Text = step.Status;
            });

            if (updating)
            {
                CurrentAction.Text = "Waiting for XXAR to close...";
                await Task.Run(() => UpdateHandoff.WaitForAppToClose(wizard.Session.Machine.InstalledRoot));
            }

            // The retry loop exists for one case only: the app was running and the user closed it.
            while (true)
            {
                try
                {
                    await Task.Run(() => RunJob(progress));
                    if (updating)
                    {
                        UpdateHandoff.Relaunch(wizard.Session.TargetRoot);
                        wizard.Close(0);
                        return;
                    }
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Success, removing));
                    return;
                }
                catch (AppRunningException)
                {
                    if (AskToRetry()) continue;
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Cancelled, removing));
                    return;
                }
                catch (OperationCanceledException)
                {
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Cancelled, removing));
                    return;
                }
                catch (Exception ex)
                {
                    Journal.Error(removing ? "uninstall failed" : "install failed", ex);
                    wizard.Session.FailureText = ex.Message;
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Failed, removing));
                    return;
                }
            }
        }

        private void RunJob(IProgress<StepProgress> progress)
        {
            if (removing)
                RemoveJob.Run(wizard.Session, progress);
            else
                InstallJob.Run(wizard.Session, progress, cancel.Token);
        }

        private bool AskToRetry()
        {
            var answer = MessageBox.Show(Window.GetWindow(this),
                "XXAR is currently running.\n\nClose it, then click Retry to continue.",
                "XXAR Installer", MessageBoxButton.OKCancel, MessageBoxImage.Warning);
            return answer == MessageBoxResult.OK;
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            // Immediate feedback: the running job stops at the next file boundary.
            Cancel.IsEnabled = false;
            CurrentAction.Text = "Cancelling...";
            cancel.Cancel();
        }
    }
}
