"""Explicit feature order and preprocessing identity for weather experiments."""
from ml.factors import ALIGNMENTS, WEATHER_MODEL_COLUMNS

GROUPS = {
    'temperature': ('temperature_2m','apparent_temperature'),
    'precipitation': ('precipitation','is_wet','precipitation_6h'),
    'snow': ('snowfall','is_snowing','near_freezing','freeze_transition'),
    'wind': ('wind_speed_10m','wind_gusts_10m'),
}


def normalize_config(config):
    if isinstance(config, dict) and config.get('schema') == 'score-improvement-v2':
        from ml.score_models import normalize_score_config
        return normalize_score_config(config)
    if not isinstance(config,dict) or set(config) - {'id','weather_groups','alignment','weather_columns','model_name','information_mode','seed'}:
        raise ValueError('Unexpected experiment configuration fields')
    groups=config.get('weather_groups',[])
    if not isinstance(groups,list) or not all(isinstance(group,str) for group in groups) or len(set(groups)) != len(groups) or set(groups)-set(GROUPS):
        raise ValueError('Unknown or duplicate weather groups')
    alignment=config.get('alignment',ALIGNMENTS[0])
    if alignment not in ALIGNMENTS:
        raise ValueError('Unknown weather alignment')
    wanted={name for group in groups for name in GROUPS[group]}
    # Legacy full variant keeps its exact original feature order.
    columns=[name for name in WEATHER_MODEL_COLUMNS if name in wanted]
    result={'id':config.get('id','custom'),'weather_groups':groups,'alignment':alignment,'weather_columns':columns,
            'model_name':'competition_weather_hgbt' if groups else 'calendar_holiday_hgbt',
            'information_mode':'competition_retro' if groups else 'operational'}
    if not isinstance(result['id'],str) or not result['id']:
        raise ValueError('Experiment ID must be a nonempty string')
    for key in ('weather_columns','model_name','information_mode'):
        if key in config and config[key] != result[key]:
            raise ValueError(f'Experiment {key} disagrees with weather groups')
    if 'seed' in config:
        if type(config['seed']) is not int:
            raise ValueError('Seed must be an integer')
        result['seed'] = config['seed']
    return result
