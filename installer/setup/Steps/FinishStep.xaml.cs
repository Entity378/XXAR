using System;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public enum FinishOutcome { Success, Cancelled, Failed, NothingToDo }

    public partial class FinishStep : UserControl
    {
        private readonly MainWindow wizard;
        private readonly FinishOutcome outcome;

        public FinishStep(MainWindow wizard, FinishOutcome outcome, bool removing)
        {
            this.wizard = wizard;
            this.outcome = outcome;
            InitializeComponent();
            Describe(outcome, removing);
        }

        private void Describe(FinishOutcome outcome, bool removing)
        {
            switch (outcome)
            {
                case FinishOutcome.Success:
                    // The XAML defaults already say the run completed.
                    break;

                case FinishOutcome.Cancelled:
                    Frame.Heading = "XXAR Installer was interrupted";
                    Frame.Subheading = removing
                        ? "The installer was interrupted before XXAR could be removed. Click Finish to exit."
                        : "The installer was interrupted before XXAR could be completely installed. Click Finish to exit.";
                    break;

                case FinishOutcome.Failed:
                    Frame.Heading = "XXAR Installer failed";
                    Frame.Subheading = (wizard.Session.FailureText ?? "An unexpected error occurred.")
                                       + "\n\nSee the log for details.";
                    break;

                case FinishOutcome.NothingToDo:
                    Frame.Heading = "XXAR is not installed";
                    Frame.Subheading = "There is nothing to remove on this computer.\n\n" +
                                       "To install XXAR, run the full installer instead.";
                    Cancel.Visibility = Visibility.Collapsed;
                    break;
            }
        }

        private void ViewLog_Click(object sender, RoutedEventArgs e)
        {
            // Absolute path: a bare name would be searched for next to the downloaded installer first.
            var notepad = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System), "notepad.exe");
            try { Process.Start(notepad, $"\"{Journal.Path}\""); }
            catch (Exception ex) { Journal.Error("could not open the log", ex); }
        }

        private void Leave_Click(object sender, RoutedEventArgs e)
        {
            wizard.Close(outcome == FinishOutcome.Success ? 0 : 1);
        }
    }
}
