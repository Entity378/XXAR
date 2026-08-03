using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using XXAR.Wizard;

namespace XXAR.Uninstall.Steps
{
    public partial class ProgressStep : UserControl
    {
        private readonly MainWindow wizard;
        private bool alreadyRan;

        public ProgressStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();
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
                    await Task.Run(() => RemovalJob.Run(wizard.Plan, progress));
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Success));
                    return;
                }
                catch (AppRunningException)
                {
                    if (AskToRetry()) continue;
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Cancelled));
                    return;
                }
                catch (Exception ex)
                {
                    Journal.Error("uninstall failed", ex);
                    wizard.Plan.FailureText = ex.Message;
                    wizard.Show(new FinishStep(wizard, FinishOutcome.Failed));
                    return;
                }
            }
        }

        // Retrying in place is friendlier than making the user start the uninstaller again.
        private bool AskToRetry()
        {
            var answer = MessageBox.Show(Window.GetWindow(this),
                "XXAR is currently running.\n\nClose it, then click OK to continue.",
                "XXAR Uninstall", MessageBoxButton.OKCancel, MessageBoxImage.Warning);
            return answer == MessageBoxResult.OK;
        }
    }
}
