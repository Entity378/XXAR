using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public partial class RemoveOptionsPage : UserControl
    {
        private readonly MainWindow host;

        public RemoveOptionsPage(MainWindow host, bool allowBack)
        {
            this.host = host;
            InitializeComponent();
            // The standalone uninstaller has no page to go back to.
            GoPrev.IsEnabled = allowBack;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => host.Go(new MaintenancePage(host));

        private void Uninstall_Click(object sender, RoutedEventArgs e)
        {
            host.Ctx.PurgeUserData = PurgeUserData.IsChecked == true;
            host.Go(new ProgressPage(host, uninstalling: true));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => host.CancelSetup();
    }
}
