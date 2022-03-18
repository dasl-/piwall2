import React from 'react';

import SwipeableList from 'component/lib/SwipeableList/SwipeableList';
import SwipeableListItem from 'component/lib/SwipeableList/SwipeableListItem';
import CurrentlyPlayingVideo from 'component/currently_playing/currently_playing_video';

class PlaylistExpanded extends React.Component {
  constructor(props) {
    super(props);

    this.onRemoveVideo = this.onRemoveVideo.bind(this);
    this.handleSkip = this.handleSkip.bind(this);
  }

  render() {
    return (
      <div className='container px-2'>
        <div className='col-12'>
          <section className=' playlist-expanded p-0 px-2 m-0'>
            <div className="w-100 text-center py-3 mb-0" onClick={this.props.contractFooterPlaylist}>
              <span className="glyphicon glyphicon-chevron-down bg-dark-text" aria-hidden="true" />
            </div>

            <CurrentlyPlayingVideo
              nextVideo={this.props.nextVideo}
              setVolPct={this.props.setVolPct}
              vol_pct={this.props.vol_pct}
              clearQueue={this.props.clearQueue}
              video={this.props.current_video}
              tv_data={this.props.tv_data}
              setDisplayMode={this.props.setDisplayMode}
              setAnimationMode={this.props.setAnimationMode}
              animation_mode={this.props.animation_mode}
            />

            <div className="play-queue">
              { (this.props.videos.length === 0) &&
                <div className='container pt-2 px-0 mt-2 playlist-video-common'>
                    <div className="py-3 text-center">
                      &lt;Nothing&gt;
                    </div>
                </div>
              }

              <SwipeableList background={<span></span>}>
              {
                this.props.videos.map((video, index) => {
                  return (
                    <SwipeableListItem
                      // append to the key to ensure the swipe menu collapses after the video has
                      // been moved to the top of the queue
                      key={video.video_id + '-' + video.priority + '-' + (index == 0 ? '0' : '1')}
                      index={index}
                      onRemoveVideo={() => this.onRemoveVideo(video)}
                      onPlayVideoNext={() => this.onPlayVideoNext(video)}
                      fullSwipeThreshold={100} // don't allow full swipes
                      openMenuSwipeThreshold={0.2}
                      closeMenuSwipeThreshold={0.05}
                      buttonWidth={100}
                      numButtons={index == 0 ? 1 : 2}
                    >
                      <div className='container px-0 playlist-video-common'>
                          <div className='row mr-0'>

                            <div className='col-6 px-2 pl-3 small-vertical-center'>
                              <img
                                className='img-fluid'
                                src={video.thumbnail}
                                alt={video.title}
                              />

                              <span className="duration badge badge-dark position-absolute mr-3 mb-1">{video.duration}</span>
                            </div>

                            <div className='col-6 px-2'>
                              <div className='video-title'>{video.title}</div>
                            </div>
                          </div>
                      </div>
                    </SwipeableListItem>
                  );
                })
              }
              </SwipeableList>
            </div>
          </section>
        </div>
      </div>
    );
  }

  onRemoveVideo(video) {
    this.props.removeVideo(video);
  }

  onPlayVideoNext(video) {
    this.props.playVideoNext(video);
  }

  // TODO playVideoNext shit

  handleSkip(e) {
    e.preventDefault();
    e.stopPropagation();
    this.props.nextVideo();
  }
}

export default PlaylistExpanded;