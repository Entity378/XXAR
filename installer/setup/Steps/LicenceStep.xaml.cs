using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class LicenceStep : UserControl
    {
        private readonly MainWindow wizard;

        public LicenceStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();
        }

        private void Step_Loaded(object sender, RoutedEventArgs e)
        {
            try
            {
                var licence = Application.GetResourceStream(new Uri("pack://application:,,,/License.rtf"));
                using (var stream = licence.Stream)
                {
                    var whole = new TextRange(LicenceText.Document.ContentStart, LicenceText.Document.ContentEnd);
                    whole.Load(stream, DataFormats.Rtf);
                }
            }
            catch (Exception ex)
            {
                Journal.Error("licence load failed", ex);
            }
        }

        private void Accept_Changed(object sender, RoutedEventArgs e)
        {
            GoNext.IsEnabled = AcceptCheckbox.IsChecked == true;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new WelcomeStep(wizard));
        }

        private void GoNext_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new DestinationStep(wizard));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Abandon();
        }
    }
}
