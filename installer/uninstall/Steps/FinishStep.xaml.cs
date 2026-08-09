using System;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using XXAR.Wizard;

namespace XXAR.Uninstall.Steps
{
    public enum FinishOutcome { Success, Cancelled, Failed, NothingToDo }

    public partial class FinishStep : UserControl
    {
        private readonly MainWindow wizard;
        private readonly FinishOutcome outcome;

        public FinishStep(MainWindow wizard, FinishOutcome outcome)
        {
            this.wizard = wizard;
            this.outcome = outcome;
            InitializeComponent();
            Describe(outcome);
        }

        private void Describe(FinishOutcome outcome)
        {
            switch (outcome)
            {
                case FinishOutcome.Success:
                    // The XAML defaults already say it was removed.
                    break;

                case FinishOutcome.Cancelled:
                    Frame.Heading = "Uninstall was interrupted";
                    Frame.Subheading = "XXAR was not completely removed. Click Finish to close.";
                    break;

                case FinishOutcome.Failed:
                    Frame.Heading = "Uninstall failed";
                    Frame.Subheading = (wizard.Plan.FailureText ?? "An unexpected error occurred.")
                                       + "\n\nSee the log for details.";
                    break;

                case FinishOutcome.NothingToDo:
                    Frame.Heading = "XXAR is not installed";
                    Frame.Subheading = "There is nothing to remove on this computer.";
                    break;
            }
        }

        private void ViewLog_Click(object sender, RoutedEventArgs e)
        {
            // Absolute path: a bare name would be searched for next to this executable first.
            var notepad = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System), "notepad.exe");
            try { Process.Start(notepad, $"\"{Journal.Path}\""); }
            catch (Exception ex) { Journal.Error("could not open the log", ex); }
        }

        private void Leave_Click(object sender, RoutedEventArgs e)
        {
            bool clean = outcome == FinishOutcome.Success || outcome == FinishOutcome.NothingToDo;
            wizard.Close(clean ? 0 : 1);
        }
    }
}
