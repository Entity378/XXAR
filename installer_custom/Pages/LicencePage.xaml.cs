using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;

namespace XXAR.Setup.Pages
{
    public partial class LicencePage : UserControl
    {
        private readonly MainWindow host;

        public LicencePage(MainWindow host)
        {
            this.host = host;
            InitializeComponent();
        }

        private void Page_Loaded(object sender, RoutedEventArgs e)
        {
            try
            {
                var info = Application.GetResourceStream(new Uri("pack://application:,,,/License.rtf"));
                using (var stream = info.Stream)
                {
                    var range = new TextRange(LicenceText.Document.ContentStart, LicenceText.Document.ContentEnd);
                    range.Load(stream, DataFormats.Rtf);
                }
            }
            catch (Exception ex)
            {
                SetupLog.Error("licence load failed", ex);
            }
        }

        private void Accept_Changed(object sender, RoutedEventArgs e)
            => GoNext.IsEnabled = AcceptCheckbox.IsChecked == true;

        private void GoPrev_Click(object sender, RoutedEventArgs e) => host.Go(new WelcomePage(host));
        private void GoNext_Click(object sender, RoutedEventArgs e) => host.Go(new InstallDirPage(host));
        private void Cancel_Click(object sender, RoutedEventArgs e) => host.CancelSetup();
    }
}
