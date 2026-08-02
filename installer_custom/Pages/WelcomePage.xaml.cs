using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public partial class WelcomePage : UserControl
    {
        private readonly MainWindow host;

        public WelcomePage(MainWindow host)
        {
            this.host = host;
            InitializeComponent();
        }

        private void GoNext_Click(object sender, RoutedEventArgs e) => host.Go(new LicencePage(host));
        private void Cancel_Click(object sender, RoutedEventArgs e) => host.CancelSetup();
    }
}
