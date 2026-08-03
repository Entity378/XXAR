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
        private readonly CancellationTokenSource cancel = new CancellationTokenSource();
        private bool alreadyRan;

        public ProgressStep(MainWindow wizard, bool removing)
        {
            this.wizard = wizard;
            this.removing = removing;
            InitializeComponent();

            if (removing)
            {
                Frame.Heading = "Removing XXAR";
                Frame.Subheading = "Please wait while XXAR is removed from your computer.";
                // Removal is quick and has no rollback; cancelling midway would only leave it half done.
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

            // The retry loop exists for one case only: the app was running and the user closed it.
            while (true)
            {
                try
                {
                    await Task.Run(() => RunJob(progress));
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
