import './currently_playing.css';
import App from '../app/app';
import api from 'api';

import 'rc-slider/assets/index.css';
import React from 'react';
import Slider from 'rc-slider';

import LoadWithVideo from '../util/load_with_video';
import TvWall from '../tv_wall/tv_wall';

import tv_config from 'tv_config.json';

class CurrentlyPlayingVideo extends React.Component {
  constructor(props) {
    super(props);
    this.handleSkip = this.handleSkip.bind(this);
    this.handleFxAllTile = this.handleFxAllTile.bind(this);
    this.handleFxAllRepeat = this.handleFxAllRepeat.bind(this);
    this.state = {
      vol_pct: this.props.vol_pct,
      is_vol_locked: false,
      is_vol_lock_releasable: true,
      vol_lock_marked_releasable_time: 0,
    };
    this.tv_wall = null;
  }

  render() {
    return (
      <div>
          <LoadWithVideo video={this.props.video}>
            <TvWall
              src={(this.props.video) ? this.props.video.thumbnail : 'img/playlist-placeholder.png'}
              alt={(this.props.video) ? this.props.video.title : ''}
              ref={ (tv_wall) => { this.tv_wall = tv_wall } }
              tv_data={this.props.tv_data}
              setDisplayMode={this.props.setDisplayMode}
            />
          </LoadWithVideo>

          <div className='text-large text-center py-2'>
            {(this.props.video)
              ? this.props.video.title
              : <span>&lt;Nothing&gt;</span>
            }
          </div>

        <div className='row'>
          <div className='col-1 p-0 text-right'><span className='glyphicon glyphicon-volume-down bg-light-text vol-icon' aria-hidden='true' /></div>
          <div className='col-10 volume-container'>
            <Slider
              className='volume'
              min={0}
              max={100}
              step={1}
              onBeforeChange={this.grabVolMutex}
              onChange={this.onVolChange}
              onAfterChange={this.markVolMutexReleasable}
              value={this.state.is_vol_locked ? this.state.vol_pct : this.props.vol_pct}
              trackStyle={{
                border: '1px solid #686E7B',
                backgroundColor: '#686E7B',
                height: 10
              }}
              railStyle={{
                border: '1px solid #686E7B',
                backgroundColor: 'transparent',
                height: 10
              }}
              handleStyle={{
                border: '1px solid #5cedf9',
                boxShadow: '0px 0px 3.5px #52c6f3, 0px 0px 0px #6acef5',
                height: 30,
                width: 30,
                marginLeft: -16,
                marginTop: -9,
                backgroundColor: '#2e3135',
              }}
            />
          </div>
          <div className='col-1 p-0'><span className='glyphicon glyphicon-volume-up bg-light-text vol-icon' aria-hidden='true' /></div>
        </div>

        <div className='container pt-1 px-0 mt-1'>
          <div className='row d-flex justify-content-center'>
            <span
              className='glyphicon glyphicon-resize-full bg-light-text video-fx-icon'
              aria-hidden='true'
              onClick={this.handleFxAllTile} data-fx='all_tile' />
            <span className='glyphicon glyphicon-resize-small bg-light-text video-fx-icon'
              aria-hidden='true'
              onClick={this.handleFxAllRepeat} data-fx='all_repeat' />
          </div>
        </div>

        <div className='container pt-1 px-0 mt-1'>
          <div className='row mr-0'>
            <div className='col-8 px-2 pl-3 small-vertical-center'>
                Up Next
            </div>
            <div className='col-3 px-0'>

            </div>
            <div className='col-1 px-0'>
                {(this.props.video) &&
                  <a href='#' className='text-light skip-icon' onClick={this.handleSkip}>
                    <span className='glyphicon glyphicon-forward bg-light-text' aria-hidden='true' />
                  </a>
                }
            </div>
          </div>
        </div>
      </div>
    );
  }

  handleSkip(e) {
    e.preventDefault();
    e.stopPropagation();
    if (this.tv_wall) {
      this.tv_wall.props.setLoading();
    }
    this.props.nextVideo();
  }

  handleFxAllTile(e) {
    e.preventDefault();
    e.stopPropagation();
    var display_mode_by_tv_id = {}
    for (const tv_id in tv_config['tvs']) {
      display_mode_by_tv_id[tv_id] = 'DISPLAY_MODE_TILE'
    }
    this.props.setDisplayMode(display_mode_by_tv_id)
  }

  handleFxAllRepeat(e) {
    e.preventDefault();
    e.stopPropagation();
    var display_mode_by_tv_id = {}
    for (const tv_id in tv_config['tvs']) {
      display_mode_by_tv_id[tv_id] = 'DISPLAY_MODE_REPEAT'
    }
    this.props.setDisplayMode(display_mode_by_tv_id)
  }

  onVolChange = (vol_pct) => {
    this.props.setVolPct(vol_pct)
    this.setState({vol_pct: vol_pct});
  };

  grabVolMutex = () => {
    this.setState({
      is_vol_locked: true,
      is_vol_lock_releasable: false
    });
  };
  markVolMutexReleasable = () => {
    this.setState({
      is_vol_lock_releasable: true,
      vol_lock_marked_releasable_time: (new Date()).getTime()
    });
  };
  releaseVolMutex = () => {
    this.setState({
      is_vol_locked: false,
      is_vol_lock_releasable: true
    });
  };

  // TODO: this is deprecated
  componentWillReceiveProps(nextProps) {
    if (this.state.is_vol_locked && this.state.is_vol_lock_releasable) {
      var millis_since_vol_locked_marked_releasable = (new Date()).getTime() - this.state.vol_lock_marked_releasable_time;
      if (millis_since_vol_locked_marked_releasable > (App.QUEUE_POLL_INTERVAL_MS + 500)) {
        this.releaseVolMutex();
      }
    }

    if (!this.state.is_vol_locked) {
      this.setState({vol_pct: nextProps.vol_pct});
    }
  };

}

export default CurrentlyPlayingVideo;
