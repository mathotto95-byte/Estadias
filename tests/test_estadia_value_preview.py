import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository, service


class EstadiaValuePreviewTest(unittest.TestCase):
    def test_default_rate_and_existing_results(self):
        params = service._params_for_trip(pd.Series({"cliente": "A"}), pd.DataFrame(), {})
        self.assertEqual(params["valor_hora"], 68.40)
        existing = pd.DataFrame({"horas_estadia": [2, 3], "valor_estimado_estadia": [0, 90]})
        with patch.object(repository, "read_filtered", return_value=existing):
            rows = repository.read_cross()
        self.assertEqual(rows["valor_estimado_estadia"].tolist(), [136.8, 90])


if __name__ == "__main__":
    unittest.main()
