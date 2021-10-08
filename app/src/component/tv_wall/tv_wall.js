import React from 'react';
import Tv from './tv';
import tv_config from 'tv_config.json';
import './tv_wall.css';

class TvWall extends React.Component {

  constructor(props) {
    super(props);
    this.state = {
      currently_playing_video_img_width: 0,
      currently_playing_video_img_height: 0,
    };
    this.scaled_tv_config = {};
  }


  render() {
    var maybe_loading_class = (this.props.loading ? 'loading' : '');
    return (
      <div className={"tv-wall-container bg-dark position-relative " + maybe_loading_class}>
        <div className='loading-cover'><div className='dot-pulse'></div></div>
        <img
          src={this.props.src}
          className='img-fluid video-thumbnail w-100'
          ref={ (currently_playing_video_img) => { this.currently_playing_video_img = currently_playing_video_img } }
          onLoad={() => {
            this.props.setImageLoaded();
            this.currentlyPlayingVideoImgSizeChanged();
          }}
          alt={this.props.alt}
        />
        <div className="tv-wall">
          {
            Object.values(this.scaled_tv_config).map((tv, index) => {
              const tv_id = tv['tv_id'];
              console.log("yoo", tv_id, this.props.tv_data);
              const this_tv_data = this.props.tv_data[tv_id] ? this.props.tv_data[tv_id] : {};
              const display_mode = 'display_mode' in this_tv_data ? this_tv_data['display_mode'] : 'DISPLAY_MODE_TILE';
              const loading = 'loading' in this_tv_data ? this_tv_data['loading'] : false;
              return (
                <Tv
                  key={index}
                  x={tv.x}
                  y={tv.y}
                  width={tv.width}
                  height={tv.height}
                  bgImgWidth={this.state.currently_playing_video_img_width}
                  bgImgHeight={this.state.currently_playing_video_img_height}
                  src={this.props.src}
                  hostname={tv.hostname}
                  tv_id={tv_id}
                  display_mode={display_mode}
                  loading={loading}
                  setDisplayMode={this.props.setDisplayMode}
                />
              );
            })
          }
        </div>

        {(this.props.video) &&
          <span className='duration badge badge-dark position-absolute mr-1 mb-1'>{this.props.video.duration}</span>
        }
      </div>
    );
  }

  componentDidMount() {
    window.addEventListener("resize", this.currentlyPlayingVideoImgSizeChanged.bind(this));
  }

  currentlyPlayingVideoImgSizeChanged() {
    const currently_playing_video_img_width = this.currently_playing_video_img.clientWidth;
    const currently_playing_video_img_height = this.currently_playing_video_img.clientHeight;
    if (currently_playing_video_img_width <= 0 || currently_playing_video_img_height <= 0) {
      return;
    }
    this.setState({
      currently_playing_video_img_width: currently_playing_video_img_width,
      currently_playing_video_img_height: currently_playing_video_img_height,
    });
    this.setScaledReceiversConfig(currently_playing_video_img_width, currently_playing_video_img_height);
  }

  /**
   * Duplication of logic also implemented in python.
   * See: ReceiverCommandBuilder::__get_video_command_crop_args
   */
  setScaledReceiversConfig(video_width, video_height) {
    const wall_width = tv_config.wall_width;
    const wall_height = tv_config.wall_height;
    const [displayable_video_width, displayable_video_height] = this.getDisplayableVideoDimensionsForScreen(
      video_width, video_height, wall_width, wall_height
    );

    const x_offset = (video_width - displayable_video_width) / 2
    const y_offset = (video_height - displayable_video_height) / 2
    console.log("tvs", tv_config.tvs);
    for (var tv_id in tv_config.tvs) {
      const this_tv_config = tv_config.tvs[tv_id];
      const x0 = x_offset + ((this_tv_config.x / wall_width) * displayable_video_width);
      const y0 = y_offset + ((this_tv_config.y / wall_height) * displayable_video_height);
      const width = (this_tv_config.width / wall_width) * displayable_video_width;
      const height = (this_tv_config.height / wall_height) * displayable_video_height;
      this.scaled_tv_config[tv_id] = {
        ...this_tv_config,
        ...{
          x: x0,
          y: y0,
          width: width,
          height: height,
        }
      }
    }
  }

  /**
   * Duplication of logic also implemented in python.
   * See: ReceiverCommandBuilder::__get_displayable_video_dimensions_for_screen
   */
  getDisplayableVideoDimensionsForScreen(video_width, video_height, screen_width, screen_height) {
    const video_aspect_ratio = video_width / video_height;
    const screen_aspect_ratio = screen_width / screen_height;

    let displayable_video_width, displayable_video_height;
    if (screen_aspect_ratio >= video_aspect_ratio) {
      displayable_video_width = video_width;
      displayable_video_height = video_width / screen_aspect_ratio;
    } else {
      displayable_video_height = video_height;
      displayable_video_width = screen_aspect_ratio * video_height;
    }
    return [displayable_video_width, displayable_video_height]
  }

}

export default TvWall;
