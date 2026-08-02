using System;
using System.IO;
using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public partial class InstallDirPage : UserControl
    {
        private readonly MainWindow host;

        public InstallDirPage(MainWindow host)
        {
            this.host = host;
            InitializeComponent();
            InstallDirPath.Text = host.Ctx.TargetDir;
        }

        private void Change_Click(object sender, RoutedEventArgs e)
        {
            var owner = new System.Windows.Interop.WindowInteropHelper(Window.GetWindow(this)).Handle;
            var chosen = FolderPicker.Pick(owner, InstallDirPath.Text);
            if (chosen != null)
                InstallDirPath.Text = chosen;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => host.Go(new LicencePage(host));

        private void GoNext_Click(object sender, RoutedEventArgs e)
        {
            var dir = InstallDirPath.Text.Trim();
            if (dir.Length == 0 || !Path.IsPathRooted(dir))
            {
                MessageBox.Show(Window.GetWindow(this), "Please enter a valid absolute folder path.",
                                "XXAR Setup", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            host.Ctx.TargetDir = dir.TrimEnd('\\');
            host.Go(new ProgressPage(host, uninstalling: false));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => host.CancelSetup();
    }
}
