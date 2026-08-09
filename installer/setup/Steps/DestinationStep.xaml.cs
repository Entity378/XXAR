using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class DestinationStep : UserControl
    {
        private readonly MainWindow wizard;

        public DestinationStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();
            ChosenFolder.Text = wizard.Session.TargetRoot;
        }

        private void Change_Click(object sender, RoutedEventArgs e)
        {
            var owner = new WindowInteropHelper(Window.GetWindow(this)).Handle;
            var picked = FolderBrowser.Browse(owner, ChosenFolder.Text);
            if (picked != null) ChosenFolder.Text = picked;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new LicenceStep(wizard));
        }

        private void GoNext_Click(object sender, RoutedEventArgs e)
        {
            var folder = ChosenFolder.Text.Trim();
            if (folder.Length == 0 || !Path.IsPathRooted(folder))
            {
                MessageBox.Show(Window.GetWindow(this), "Please enter a valid absolute folder path.",
                                "XXAR Installer", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            wizard.Session.TargetRoot = folder.TrimEnd('\\');
            wizard.Show(new ProgressStep(wizard, removing: false));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Abandon();
        }
    }
}
