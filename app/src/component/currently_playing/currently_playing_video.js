import './currently_playing.css';
import App from '../app/app';
import api from 'api';

import 'rc-slider/assets/index.css';
import React from 'react';
import Slider from 'rc-slider';

import LoadWithVideo from '../util/load_with_video';
import TvWall from '../tv_wall/tv_wall';
import VfxButton from '../vfx_button/vfx_button';
import SvgButton from '../vfx_button/svg_button';

class CurrentlyPlayingVideo extends React.Component {
  constructor(props) {
    super(props);
    this.handleSkip = this.handleSkip.bind(this);
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

          <h2 className='text-center py-2'>
            {(this.props.video)
              ? this.props.video.title
              : <span>&lt;Nothing&gt;</span>
            }
          </h2>

          <div className='container animation-container pt-1 px-0 mt-1'>
          <div className='row d-flex justify-content-center'>
            <SvgButton
              button_animation_mode='ANIMATION_MODE_TILE'
              setAnimationMode={this.props.setAnimationMode}
              app_animation_mode={this.props.animation_mode}
            />
            <SvgButton
              button_animation_mode='ANIMATION_MODE_REPEAT'
              setAnimationMode={this.props.setAnimationMode}
              app_animation_mode={this.props.animation_mode}
            />
            <SvgButton
              button_animation_mode='ANIMATION_MODE_TILE_REPEAT'
              setAnimationMode={this.props.setAnimationMode}
              app_animation_mode={this.props.animation_mode}
            />
          </div>
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
            />
          </div>
          <div className='col-1 p-0'><span className='glyphicon glyphicon-volume-up bg-light-text vol-icon' aria-hidden='true' /></div>
        </div>



        <div className='container pt-5 px-0 mt-1'>
          <div className='row mr-0 pt-2 up-next'>
            <h3 className='col-8 px-2 pl-3 small-vertical-center'>
                Up Next
            </h3>
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
