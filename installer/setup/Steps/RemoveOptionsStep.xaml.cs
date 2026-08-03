using System.Windows;
using System.Windows.Controls;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class RemoveOptionsStep : UserControl
    {
        private readonly MainWindow wizard;

        public RemoveOptionsStep(MainWindow wizard, bool allowBack)
        {
            this.wizard = wizard;
            InitializeComponent();
            // Started with /uninstall there is no earlier step to go back to.
            GoPrev.IsEnabled = allowBack;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new MaintenanceStep(wizard));
        }

        private void Remove_Click(object sender, RoutedEventArgs e)
        {
            wizard.Session.PurgeUserData = PurgeUserData.IsChecked == true;
            wizard.Show(new ProgressStep(wizard, removing: true));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Abandon();
        }
    }
}
