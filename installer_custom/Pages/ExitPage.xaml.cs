using System;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public enum ExitOutcome { Success, Cancelled, Failed, NothingToDo }

    public partial class ExitPage : UserControl
    {
        private readonly MainWindow host;
        private readonly ExitOutcome outcome;

        public ExitPage(MainWindow host, ExitOutcome outcome, bool uninstalling)
        {
            this.host = host;
            this.outcome = outcome;
            InitializeComponent();

            switch (outcome)
            {
                case ExitOutcome.Success:
                    // Defaults in the XAML already read "Completed the XXAR Setup Wizard".
                    break;
                case ExitOutcome.Cancelled:
                    DialogTitleLabel.Text = "XXAR Setup was interrupted";
                    DialogDescription.Text = uninstalling
                        ? "The wizard was interrupted before XXAR could be removed. Click Finish to exit."
                        : "The wizard was interrupted before XXAR could be completely installed. Click Finish to exit.";
                    break;
                case ExitOutcome.Failed:
                    DialogTitleLabel.Text = "XXAR Setup failed";
                    DialogDescription.Text = (host.Ctx.FailureText ?? "An unexpected error occurred.")
                                             + "\n\nSee the log for details.";
                    break;
                case ExitOutcome.NothingToDo:
                    DialogTitleLabel.Text = "XXAR is not installed";
                    DialogDescription.Text = "There is nothing to remove on this computer.\n\n" +
                                             "To install XXAR, run the full XXAR-Setup installer instead.";
                    Cancel.Visibility = Visibility.Collapsed;
                    break;
            }
        }

        private void ViewLog_Click(object sender, RoutedEventArgs e)
        {
            // Absolute path: a bare name would be searched for next to the downloaded setup first.
            var notepad = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System), "notepad.exe");
            try { Process.Start(notepad, $"\"{SetupLog.Path}\""); } catch { }
        }

        private void GoExit_Click(object sender, RoutedEventArgs e)
            => host.FinishSetup(outcome == ExitOutcome.Success ? 0 : 1);
    }
}
