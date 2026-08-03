using System.Windows;
using System.Windows.Controls;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class WelcomeStep : UserControl
    {
        private readonly MainWindow wizard;

        public WelcomeStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();
        }

        private void GoNext_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new LicenceStep(wizard));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Abandon();
        }
    }
}
