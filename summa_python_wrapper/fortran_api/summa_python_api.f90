! SUMMA_PY_API_PR675
!
! Thin Python interface for SUMMA PR675.
! Python owns optimization; SUMMA owns model initialization,
! spin-up, parameter fields, constraints and simulation.
!
! Phase 1: initialize one independent SUMMA worker.

module summa_python_api

  use, intrinsic :: iso_c_binding, only: c_int, c_char, c_null_char, c_double

  use mpi, only: MPI_COMM_SELF, MPI_SUCCESS
  use mpi, only: MPI_Initialized, MPI_Init
  use mpi, only: MPI_Finalized, MPI_Finalize

  use nr_type, only: i4b, rkind
  use data_types, only: gru_hru_dom_doublevec, gru_double
  use summa_type, only: config_info, parallel_context_type

  use mpi_context, only: set_mpi_context
  use summa_init, only: init_config
  use summa_spinup, only: spinup_from_cold

  use summa_parameter_spec, only: get_summa_parameter_spec
  use parameter_search, only: parameter_spec
  use parameter_search, only: parameter_search_info
  use parameter_search, only: initialize_parameter_search

  use model_calibration, only: is_feasible
  use summa_simulation, only: evaluate_objectives
  use summa_parameter_fields, only: summa_parameter_map
  use summa_parameter_fields, only: summa_calibration_adapter
  use summa_parameter_fields, only: initialize_summa_calibration_adapter
  use summa_parameter_fields, only: apply_summa_calibration_adapter
  use calibration_output_module, only: create_calibration_output
  use calibration_output_module, only: write_calibration_output
  use calibration_output_module, only: close_calibration_output
  use summa_parameter_export, only: write_physical_trial_parameters

  use globalData, only: iRunMode, iRunModeFull
  use globalData, only: startGRU, integerMissing
  use globalData, only: restart_filename
  use summaFileManager, only: MODEL_INITCOND

  implicit none
  private

  public :: summa_py_api_version
  public :: summa_py_init
  public :: summa_py_set_run_index
  public :: summa_py_finalize
  public :: summa_py_nparameters
  public :: summa_py_get_parameter
  public :: summa_py_check_feasibility
  public :: summa_py_evaluate
  public :: summa_py_get_defaults
  public :: summa_py_set_optimizer
  public :: summa_py_output_open
  public :: summa_py_output_write
  public :: summa_py_output_close
  public :: summa_py_export_best

  type(config_info), save :: config_saved
  type(parallel_context_type), save :: domain_parallel
  type(parallel_context_type), save :: instance_parallel

  type(parameter_spec), save :: spec_saved
  type(parameter_search_info), save :: search_saved
  type(summa_calibration_adapter), save :: adapter_saved

  type(gru_hru_dom_doublevec), save :: mpar_init_saved
  type(gru_double), save :: bpar_init_saved
  type(summa_parameter_map), allocatable, save :: param_map_saved(:)
  integer(i4b), save :: output_ncid = -1
  logical, save :: output_open = .false.
  character(len=64), save :: python_optimizer = ''

  logical, save :: initialized = .false.
  logical, save :: mpi_owned = .false.
  integer(i4b), save :: evaluation_count = 0
  integer(i4b), save :: python_run_index = 1

contains

  integer(c_int) function summa_py_api_version() &
      bind(C, name="summa_py_api_version")

    summa_py_api_version = 675_c_int

  end function summa_py_api_version


  integer(c_int) function summa_py_set_run_index(run_index) &
      bind(C,name="summa_py_set_run_index")

    integer(c_int), value :: run_index

    summa_py_set_run_index = 1_c_int

    if(initialized) return
    if(run_index < 1) return

    python_run_index = int(run_index,i4b)
    summa_py_set_run_index = 0_c_int

  end function summa_py_set_run_index


  integer(c_int) function summa_py_init(config_path_c, message_c, message_len) &
      bind(C, name="summa_py_init")

    character(kind=c_char), intent(in)  :: config_path_c(*)
    character(kind=c_char), intent(out) :: message_c(*)
    integer(c_int), value :: message_len

    type(gru_hru_dom_doublevec) :: mpar_init
    type(gru_double) :: bpar_init
    type(summa_parameter_map), allocatable :: param_map(:)

    character(len=:), allocatable :: config_path
    character(len=1024) :: message
    character(len=1024) :: mpi_message

    integer(i4b) :: err, mpi_err
    logical :: mpi_started, single_domain

    summa_py_init = 0_c_int
    message = ''

    if(initialized)then
      call put_message('SUMMA worker already initialized',message_c,message_len)
      return
    endif

    ! Initialize MPI once in this independent Python process.
    call MPI_Initialized(mpi_started,mpi_err)
    if(mpi_err/=MPI_SUCCESS)then
      call put_message('MPI_Initialized failed',message_c,message_len)
      summa_py_init = 10_c_int
      return
    endif

    if(.not.mpi_started)then
      call MPI_Init(mpi_err)
      if(mpi_err==MPI_SUCCESS) mpi_owned = .true.
      if(mpi_err/=MPI_SUCCESS)then
        call put_message('MPI_Init failed',message_c,message_len)
        summa_py_init = 11_c_int
        return
      endif
    endif

    domain_parallel%comm = MPI_COMM_SELF
    instance_parallel%comm = MPI_COMM_SELF

    call set_mpi_context(domain_parallel%comm, &
                         domain_parallel%rank, &
                         domain_parallel%size,mpi_err,mpi_message)
    if(mpi_err/=MPI_SUCCESS)then
      call put_message(trim(mpi_message),message_c,message_len)
      summa_py_init = 12_c_int
      return
    endif

    call set_mpi_context(instance_parallel%comm, &
                         instance_parallel%rank, &
                         instance_parallel%size,mpi_err,mpi_message)
    if(mpi_err/=MPI_SUCCESS)then
      call put_message(trim(mpi_message),message_c,message_len)
      summa_py_init = 13_c_int
      return
    endif

    call from_c_string(config_path_c,config_path)

    if(len_trim(config_path)==0)then
      call put_message('Empty TOML configuration path',message_c,message_len)
      summa_py_init = 14_c_int
      return
    endif

    config_saved%read_cli = .false.
    config_saved%config_file = trim(config_path)
    config_saved%is_case_root = .true.
    config_saved%run_index = python_run_index

    call get_environment_variable('PWD',config_saved%cwd)

    ! Match native full-domain selection for coupled SUMMA-mizuRoute.
    ! All GRUs must be included to preserve the upstream river network.
    iRunMode = iRunModeFull
    startGRU = 1
    config_saved%nGRU_user = integerMissing

    ! Native SUMMA configuration and metadata.
    call init_config(config_saved,err,message)
    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      summa_py_init = int(err,c_int)
      return
    endif

    config_saved%read_config = .false.

    ! Native one-year reference spin-up.
    call spinup_from_cold(config_saved,domain_parallel,instance_parallel, &
                          mpar_init,bpar_init,err,message)
    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      summa_py_init = int(err,c_int)
      return
    endif

    ! Reuse the native spin-up restart for all trial evaluations.
    MODEL_INITCOND = trim(restart_filename)

    ! Match the native single-domain parameter initialization.
    single_domain = (size(mpar_init%gru)==1 .and. size(bpar_init%gru)==1)

    if(single_domain)then
      single_domain = (size(mpar_init%gru(1)%hru)==1)
    endif

    if(single_domain)then
      single_domain = (size(mpar_init%gru(1)%hru(1)%dom)==1)
    endif

    if(single_domain)then
      call get_summa_parameter_spec(config_saved,spec_saved,param_map, &
           mpar_init=mpar_init%gru(1)%hru(1)%dom(1), &
           bpar_init=bpar_init%gru(1),err=err,message=message)
    else
      call get_summa_parameter_spec(config_saved,spec_saved,param_map, &
                                    err=err,message=message)
    endif

    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      summa_py_init = int(err,c_int)
      return
    endif

    call initialize_parameter_search(spec_saved,search_saved,err,message)

    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      summa_py_init = int(err,c_int)
      return
    endif

    ! Native physical fields, ratios, multipliers and constraints.
    call initialize_summa_calibration_adapter( &
         spec_saved,search_saved,param_map, &
         mpar_init,bpar_init,adapter_saved,err,message)

    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      summa_py_init = int(err,c_int)
      return
    endif

    mpar_init_saved = mpar_init
    bpar_init_saved = bpar_init
    param_map_saved = param_map

    initialized = .true.
    call put_message('SUMMA initialization successful',message_c,message_len)

  end function summa_py_init


  integer(c_int) function summa_py_finalize() &
      bind(C, name="summa_py_finalize")

    logical :: was_finalized
    integer :: mpi_err

    summa_py_finalize = 0_c_int

    ! Only finalize MPI when this wrapper initialized it.
    if(.not.mpi_owned) return

    call MPI_Finalized(was_finalized,mpi_err)

    if(mpi_err/=MPI_SUCCESS)then
      summa_py_finalize = int(mpi_err,c_int)
      return
    endif

    if(.not.was_finalized)then
      call MPI_Finalize(mpi_err)
      summa_py_finalize = int(mpi_err,c_int)
    endif

    mpi_owned = .false.

  end function summa_py_finalize



  integer(c_int) function summa_py_nparameters() &
      bind(C, name="summa_py_nparameters")

    summa_py_nparameters = 0_c_int
    if(.not.initialized) return
    summa_py_nparameters = int(size(search_saved%param_names),c_int)

  end function summa_py_nparameters


  integer(c_int) function summa_py_get_parameter( &
      index, name_c, name_len, transform_c, transform_len, &
      lower, upper, search_lower, search_upper) &
      bind(C, name="summa_py_get_parameter")

    integer(c_int), value :: index, name_len, transform_len
    character(kind=c_char), intent(out) :: name_c(*), transform_c(*)
    real(c_double), intent(out) :: lower, upper
    real(c_double), intent(out) :: search_lower, search_upper
    integer :: i

    summa_py_get_parameter = 1_c_int
    if(.not.initialized) return

    i=int(index)
    if(i<1 .or. i>size(search_saved%param_names)) return

    call put_message(trim(search_saved%param_names(i)),name_c,name_len)
    call put_message(trim(search_saved%transformation(i)), &
                     transform_c,transform_len)

    lower=search_saved%lower(i)
    upper=search_saved%upper(i)
    search_lower=search_saved%search_lower(i)
    search_upper=search_saved%search_upper(i)

    summa_py_get_parameter=0_c_int

  end function summa_py_get_parameter


  integer(c_int) function summa_py_check_feasibility( &
      nparam, x, feasible_c, message_c, message_len) &
      bind(C, name="summa_py_check_feasibility")

    integer(c_int), value :: nparam, message_len
    real(c_double), intent(in) :: x(*)
    integer(c_int), intent(out) :: feasible_c
    character(kind=c_char), intent(out) :: message_c(*)

    logical :: feasible
    integer(i4b) :: err
    character(len=1024) :: message

    feasible_c=0_c_int
    summa_py_check_feasibility=1_c_int

    if(.not.initialized)then
      call put_message('SUMMA not initialized',message_c,message_len)
      return
    endif

    if(nparam/=size(search_saved%param_names))then
      call put_message('Incorrect parameter count',message_c,message_len)
      return
    endif

    call is_feasible(adapter_saved%calibration, &
                     x(1:nparam),feasible,err,message)

    summa_py_check_feasibility=int(err,c_int)
    if(feasible .and. err==0) feasible_c=1_c_int
    call put_message(trim(message),message_c,message_len)

  end function summa_py_check_feasibility


  integer(c_int) function summa_py_evaluate( &
      nparam, x, max_objectives, objectives_c, nout, failed_c, &
      message_c, message_len) bind(C, name="summa_py_evaluate")

    integer(c_int), value :: nparam, max_objectives, message_len
    real(c_double), intent(in) :: x(*)
    real(c_double), intent(out) :: objectives_c(*)
    integer(c_int), intent(out) :: nout, failed_c
    character(kind=c_char), intent(out) :: message_c(*)

    real(rkind), allocatable :: objectives(:)
    character(len=64) :: empty_names(0)
    real(rkind) :: empty_values(0)
    character(len=1024) :: message
    integer(i4b) :: err
    logical :: feasible, failed
    integer :: i

    summa_py_evaluate=1_c_int
    nout=0_c_int
    failed_c=1_c_int

    if(.not.initialized)then
      call put_message('SUMMA not initialized',message_c,message_len)
      return
    endif

    if(nparam/=size(search_saved%param_names))then
      call put_message('Incorrect parameter count',message_c,message_len)
      return
    endif

    ! SUMMA owns all physical feasibility checks.
    call is_feasible(adapter_saved%calibration, &
                     x(1:nparam),feasible,err,message)

    if(err/=0)then
      summa_py_evaluate=int(err,c_int)
      call put_message(trim(message),message_c,message_len)
      return
    endif

    if(.not.feasible)then
      summa_py_evaluate=0_c_int
      call put_message('Candidate infeasible',message_c,message_len)
      return
    endif

    ! Supply the accepted native physical parameter vector.
    adapter_saved%calibration%values=x(1:nparam)

    evaluation_count=evaluation_count+1

    ! Use the native adapter for field application and simulation.
    call evaluate_objectives( &
         config_saved,domain_parallel,instance_parallel, &
         evaluation_count,empty_names,empty_values,objectives, &
         trial_failed=failed,calibration=adapter_saved, &
         err=err,message=message)

    summa_py_evaluate=int(err,c_int)

    if(err/=0)then
      call put_message(trim(message),message_c,message_len)
      return
    endif

    if(.not.allocated(objectives))then
      call put_message('No objectives returned',message_c,message_len)
      summa_py_evaluate=2_c_int
      return
    endif

    if(size(objectives)>max_objectives)then
      call put_message('Objective buffer too small',message_c,message_len)
      summa_py_evaluate=3_c_int
      return
    endif

    nout=int(size(objectives),c_int)
    do i=1,size(objectives)
      objectives_c(i)=objectives(i)
    enddo

    failed_c=0_c_int
    if(failed) failed_c=1_c_int

    call put_message(trim(message),message_c,message_len)

  end function summa_py_evaluate



  ! Return initialized physical defaults, in sampled parameter order.
  integer(c_int) function summa_py_get_defaults(nparam,x,message_c,message_len) &
      bind(C,name="summa_py_get_defaults")
    integer(c_int), value :: nparam,message_len
    real(c_double), intent(out) :: x(*)
    character(kind=c_char), intent(out) :: message_c(*)
    integer :: i,j
    logical :: found

    summa_py_get_defaults = 1_c_int
    if(.not.initialized) return
    if(nparam/=size(search_saved%param_names)) return

    do i=1,nparam
      found=.false.
      do j=1,size(spec_saved%params)
        if(trim(spec_saved%params(j)%name)/= &
           trim(search_saved%param_names(i))) cycle
        if(.not.spec_saved%params(j)%sampled) cycle
        x(i)=spec_saved%params(j)%trial_value
        found=.true.
        exit
      enddo
      if(.not.found)then
        call put_message('Default parameter not found',message_c,message_len)
        return
      endif
    enddo

    summa_py_get_defaults = 0_c_int
    call put_message('OK',message_c,message_len)
  end function summa_py_get_defaults


  integer(c_int) function summa_py_set_optimizer( &
      optimizer_c,message_c,message_len) &
      bind(C,name="summa_py_set_optimizer")

    character(kind=c_char), intent(in) :: optimizer_c(*)
    character(kind=c_char), intent(out) :: message_c(*)
    integer(c_int), value :: message_len

    character(len=:), allocatable :: optimizer

    summa_py_set_optimizer=1_c_int

    if(.not.initialized)then
      call put_message('SUMMA is not initialized',message_c,message_len)
      return
    endif

    if(output_open)then
      call put_message('Calibration output is already open', &
                       message_c,message_len)
      return
    endif

    call from_c_string(optimizer_c,optimizer)

    optimizer=trim(adjustl(optimizer))

    if(len_trim(optimizer)==0 .or. len_trim(optimizer)>64)then
      call put_message('Invalid optimizer name',message_c,message_len)
      return
    endif

    python_optimizer=optimizer

    summa_py_set_optimizer=0_c_int

    call put_message('Optimizer selected: '//trim(optimizer), &
                     message_c,message_len)

  end function summa_py_set_optimizer


  integer(c_int) function summa_py_output_open(path_c,ntrials,message_c,message_len) &
      bind(C,name="summa_py_output_open")
    character(kind=c_char), intent(in) :: path_c(*)
    integer(c_int), value :: ntrials,message_len
    character(kind=c_char), intent(out) :: message_c(*)
    character(len=:), allocatable :: path
    character(len=1024) :: message
    integer(i4b) :: err

    summa_py_output_open=1_c_int
    if(.not.initialized .or. output_open .or. ntrials<1) return
    call from_c_string(path_c,path)

    if(len_trim(python_optimizer)==0)then
      python_optimizer=trim(config_saved%calib%algorithm)
    endif

    call create_calibration_output(path,spec_saved,int(ntrials,i4b), &
         1_i4b,1_i4b,1_i4b,config_saved%case_name, &
         config_saved%calib%targets,trim(python_optimizer), &
         config_saved%calib%nsga2%population_size,output_ncid,err,message)

    summa_py_output_open=int(err,c_int)
    if(err==0) output_open=.true.
    call put_message(trim(message),message_c,message_len)
  end function summa_py_output_open


  integer(c_int) function summa_py_output_write( &
      trial,nparam,x,nobj,objectives,failed_c,start_time,end_time, &
      message_c,message_len) bind(C,name="summa_py_output_write")
    integer(c_int), value :: trial,nparam,nobj,failed_c,message_len
    real(c_double), intent(in) :: x(*),objectives(*)
    integer(c_int), intent(in) :: start_time(8),end_time(8)
    character(kind=c_char), intent(out) :: message_c(*)
    character(len=1024) :: message
    integer(i4b) :: err

    summa_py_output_write=1_c_int
    if(.not.output_open) return
    if(nparam/=size(search_saved%param_names)) return
    if(nobj/=size(config_saved%calib%targets)) return

    call write_calibration_output( &
         output_ncid,int(trial,i4b),0_i4b,search_saved%param_names, &
         x(1:nparam),objectives(1:nobj),failed_c/=0, &
         int(start_time,i4b),int(end_time,i4b),err,message)

    summa_py_output_write=int(err,c_int)
    call put_message(trim(message),message_c,message_len)
  end function summa_py_output_write


  integer(c_int) function summa_py_output_close(message_c,message_len) &
      bind(C,name="summa_py_output_close")
    integer(c_int), value :: message_len
    character(kind=c_char), intent(out) :: message_c(*)
    character(len=1024) :: message
    integer(i4b) :: err

    summa_py_output_close=0_c_int
    if(.not.output_open) return

    call close_calibration_output(output_ncid,err,message)
    summa_py_output_close=int(err,c_int)
    if(err==0)then
      output_open=.false.
      output_ncid=-1
    endif
    call put_message(trim(message),message_c,message_len)
  end function summa_py_output_close


  integer(c_int) function summa_py_export_best( &
      path_c,trial,nparam,x,message_c,message_len) &
      bind(C,name="summa_py_export_best")
    character(kind=c_char), intent(in) :: path_c(*)
    integer(c_int), value :: trial,nparam,message_len
    real(c_double), intent(in) :: x(*)
    character(kind=c_char), intent(out) :: message_c(*)
    type(gru_hru_dom_doublevec) :: mpar_trial
    type(gru_double) :: bpar_trial
    character(len=:), allocatable :: path
    character(len=1024) :: message
    integer(i4b) :: err
    logical :: feasible

    summa_py_export_best=1_c_int
    if(.not.initialized) return
    if(nparam/=size(search_saved%param_names)) return

    call is_feasible(adapter_saved%calibration, &
         x(1:nparam),feasible,err,message)
    if(err/=0 .or. .not.feasible)then
      call put_message('Best candidate is infeasible',message_c,message_len)
      return
    endif

    adapter_saved%calibration%values=x(1:nparam)
    mpar_trial=mpar_init_saved
    bpar_trial=bpar_init_saved

    call apply_summa_calibration_adapter( &
         adapter_saved,mpar_trial,bpar_trial,err,message)
    if(err==0)then
      call from_c_string(path_c,path)
      call write_physical_trial_parameters( &
           path,config_saved%trial_param_names, &
           spec_saved,param_map_saved,mpar_trial,bpar_trial, &
           int(trial,i4b),err,message)
    endif

    summa_py_export_best=int(err,c_int)
    call put_message(trim(message),message_c,message_len)
  end function summa_py_export_best


  subroutine from_c_string(c_string,f_string)

    character(kind=c_char), intent(in) :: c_string(*)
    character(len=:), allocatable, intent(out) :: f_string

    integer :: i,n

    n=0
    do i=1,4096
      if(c_string(i)==c_null_char) exit
      n=n+1
    enddo

    allocate(character(len=n) :: f_string)

    do i=1,n
      f_string(i:i)=c_string(i)
    enddo

  end subroutine from_c_string


  subroutine put_message(message,message_c,message_len)

    character(*), intent(in) :: message
    character(kind=c_char), intent(out) :: message_c(*)
    integer(c_int), value :: message_len

    integer :: i,n

    if(message_len<=0) return

    do i=1,message_len
      message_c(i)=c_null_char
    enddo

    n=min(len_trim(message),int(message_len)-1)

    do i=1,n
      message_c(i)=message(i:i)
    enddo

  end subroutine put_message

end module summa_python_api
