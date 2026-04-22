using System.Diagnostics;
using System.Windows;
using WixSharp;
using WixSharp.UI.Forms;
using WixSharp.UI.WPF;
using IO = System.IO;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARExitDialog : WpfDialog, IWpfDialog
    {
        private Model model;

        public XXARExitDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            UpdateTitles(ManagedFormHost.Runtime.Session);
            model = new Model { Host = ManagedFormHost };
            DataContext = model;
        }

        public void UpdateTitles(ISession session)
        {
            if (Shell.UserInterrupted || Shell.Log.Contains("User canceled installation."))
            {
                DialogTitleLabel.Text = "[UserExitTitle]";
                DialogDescription.Text = "[UserExitDescription1]";
            }
            else if (Shell.ErrorDetected)
            {
                DialogTitleLabel.Text = "[FatalErrorTitle]";
                DialogDescription.Text = Shell.CustomErrorDescription ?? "[FatalErrorDescription1]";
            }
            this.Localize();
        }

        private void ViewLog_Click(object sender, RoutedEventArgs e) => model?.ViewLog();
        private void GoExit_Click(object sender, RoutedEventArgs e) => model?.GoExit();
        private void Cancel_Click(object sender, RoutedEventArgs e) => model?.Cancel();

        private class Model
        {
            public ManagedForm Host;
            private ISession session => Host?.Runtime?.Session;
            private IManagedUIShell shell => Host?.Shell;

            public void GoExit() => shell?.Exit();
            public void Cancel() => shell?.Exit();

            public void ViewLog()
            {
                if (shell == null) return;
                try
                {
                    var logFile = session.LogFile;
                    if (string.IsNullOrEmpty(logFile))
                    {
                        var dir = IO.Path.Combine(IO.Path.GetTempPath(), "WixSharp");
                        if (!IO.Directory.Exists(dir)) IO.Directory.CreateDirectory(dir);
                        logFile = IO.Path.Combine(dir, Host.Runtime.ProductName + ".log");
                        IO.File.WriteAllText(logFile, shell.Log);
                    }
                    Process.Start("notepad.exe", logFile);
                }
                catch
                {
                    // intentionally swallowed — log viewer is a nice-to-have, not critical
                }
            }
        }
    }
}
